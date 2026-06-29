# WorkTrace WebView UI Phase History (Archive)

> **Archive — historical phase log.** This file is the long-form record of
> every completed WebView migration phase (Phase 0A → Phase 5B.1). It is kept
> for reference and traceability only. For the current state, read
> [`docs/current-state.md`](../current-state.md); for architecture decisions,
> read [`docs/ui-webview-migration.md`](../ui-webview-migration.md).
>
> This file intentionally retains every phase label, "Implemented Scope",
> and "Not Implemented" section verbatim so each phase remains auditable.

## Status (frozen historical snapshot)

> This `## Status` block was captured when the migration doc was archived.
> The **live current phase** is in
> [`../current-state.md`](../current-state.md) (now Phase 5B.1). Treat the
> list below as a historical narrative, not a live status claim; this
> archive also contains the later Phase 4A / 4A.1 / 4B / 4B.1 / 5A / 5A.1 /
> 5B / 5B.1 sections below.

- Phase at archive time: 3C.1 (Overview fully migrated; Timeline read-only page
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
  implemented; Timeline batch project editing hardening — service
  transaction rollback on rowcount 0 / mid-transaction exception, mixed
  invalid selection rejection, duplicate id dedup, exact max boundary,
  assignment semantics match single-edit, resource rows and session notes
  unchanged, API non-ValueError exception collapse, bridge error
  convergence, frontend stale selection pruning / auto-refresh / session
  and date switch reset / dirty-state guard / saving-state reset —
  implemented; Timeline batch note editing foundation — the second batch
  write capability: multiple closed activities in the correction shell can
  have their note overwritten to the same value via an atomic transaction
  with rowcount guard and full rollback, rejecting in-progress / hidden /
  deleted activities; only `activity_log.note` and `updated_at` are
  modified (`source` is intentionally not changed); empty string is
  allowed and clears notes — implemented; Timeline batch note editing
  hardening — explicit tests for source-not-changed-to-manual, complete
  service→API error code mapping table, non-ValueError exception collapse,
  API/bridge return payload note-content leak prevention, bridge
  updated_count matches deduped selection, frontend cross-save guard,
  session/date/shell switch clearing the note textarea, and failure-path
  textarea preservation — implemented; Timeline single activity restore
  foundation — a single hidden or soft-deleted closed activity can be
  restored to visible + not-deleted via a single atomic UPDATE setting
  `is_hidden = 0` and `is_deleted = 0` with a rowcount guard; a read-only
  recovery list returns display-safe fields for hidden/deleted activities
  for the current date; only `is_hidden` / `is_deleted` / `updated_at` are
  modified; no batch restore, undo stack, or permanent delete —
  implemented; Timeline correction shell consolidation — reorganized the
  shell's internal UI into unified cards (context / activity /
  single-action / batch-action / restore / not-implemented) with stable
  IDs, shared `.correction-shell-card` styling, unified display-safe
  helper (`safeText`), and a cross-save guard
  (`isAnyCorrectionWriteSaving`) blocking batch project / batch note /
  single restore saves with `请等待当前操作完成` — implemented; Timeline
  correction shell consolidation hardening — unified cross-save guard
  message, auto-refresh re-render guard, and render-section status
  preservation during in-flight saves — implemented; Timeline UI release
  stabilization (Phase 3C) — stabilization-only: unified Timeline list /
  detail / edit / correction-shell status semantics (loading / empty /
  error / success / info / saving), additive unified status-type CSS
  classes (`.edit-status-info` / `.edit-status-loading` /
  `.edit-status-empty`), closed four `err.message` leaks in
  `loadTimeline` / `refreshAll` catch blocks so raw exception text never
  reaches the UI, and additive unified status helpers
  (`setTimelineStatus` / `setDetailStatus` / `setEditStatus` /
  `setCorrectionStatus`) delegating to existing per-area helpers without
  changing any DOM contract; no new backend write capability, bridge /
  API / service method, DB schema, correction action, batch
  hide / delete / restore, undo stack, permanent delete, batch
  time / split / merge, note append / merge, auto-rule, global overlap
  detection, or Statistics / Export / Project Rules / Settings / Privacy
  migration — implemented; Timeline UI release hardening / regression
  (Phase 3C.1) — hardening-only / regression-only: hardens the Phase 3C
  status helpers (`applyStatusType` now preserves non-status structural
  classes via a whitelisted `STATUS_TYPE_CLASS_VALUES` filter so toggling
  a status type never wipes structural classes like
  `correction-shell-status`; `statusClassFor` returns a safe default for
  unknown types), closes the last raw-exception leak surface (the
  `saveEdit` `Promise.allSettled` rejection handler no longer reads
  `.reason.message` and uses the stable `保存失败` fallback so a raw
  pywebview exception never reaches the UI), unifies all Timeline
  catch-path fallback strings to a stable short Chinese vocabulary
  (`加载时间线失败` / `刷新失败` / `加载详情失败` / `保存失败` /
  `操作失败` / `恢复失败`) so the seven older longer strings are gone,
  and adds 43 regression tests locking status-helper hardening,
  raw-exception leak prevention, stable fallback vocabulary, auto-refresh
  dirty/saving guards, display-safe rendering, CSS state hardening, and
  boundary regression locks; no new backend write capability, bridge /
  API / service method, DB schema, correction action, batch
  hide / delete / restore, undo stack, permanent delete, batch
  time / split / merge, note append / merge, auto-rule, global overlap
  detection, or Statistics / Export / Project Rules / Settings / Privacy
  migration — implemented; WebView is the default and only shipping UI).
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
- Phase 4: Statistics / Export. Phase 4A — read-only WebView migration
  foundation — is **completed**: the Statistics / Export page is migrated
  from the legacy Tkinter placeholder to a read-only WebView page that
  shows statistics summary cards, grouped tables (by project / by app /
  by status), and an export preview. No export write action, no file
  creation, no save dialog, no DB schema change, and no write API is
  introduced in Phase 4A. Phase 4A.1 — read-only hardening — is
  **completed**: loading double-click guard, client-side date range
  validator, status inclusion semantics, bool/None/non-string rejection,
  and stable tie-breaker are added without any new write capability.
  Phase 4B — Export actions foundation — CSV export only — is
  **completed**: the first controlled file-write capability is
  introduced on the Statistics / Export page. The user picks a save
  location through a native pywebview save dialog and exports the
  current closed, non-hidden, non-deleted activities in the chosen date
  range as a display-safe CSV file (UTF-8 BOM, Chinese headers,
  formula-injection escaping, no raw window title / file path / note).
  Excel / PDF / timesheet export, folder opening, auto-open, and
  auto-submit remain explicitly unsupported.
- Phase 4B.1 — CSV export hardening / native dialog + packaging validation —
  is **completed**: this is a hardening-only phase on top of Phase 4B. It
  adds no new export format and no new product feature; it locks the save
  dialog compatibility (all `create_file_dialog` return shapes, missing
  constants, exceptions -> stable Chinese `导出失败`), verifies the
  `.csv` suffix is preserved case-insensitively, hardens the frontend
  static contract (independent load/export state, no raw exception reads,
  no forbidden handlers), closes the Phase 4B packaging gap with a full
  PyInstaller / installer validation pass, and updates documentation
  boundaries. The runtime behavior of Phase 4B is unchanged.
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

## Phase 3B.6.1 Implemented Scope

Phase 3B.6.1 is a **hardening-only** phase for the Phase 3B.6 batch project
reassignment. It introduces **no new features** and **no new batch write
types**. The existing batch project reassignment is hardened across the
service transaction, API error mapping, bridge error convergence, and
frontend stale selection / auto-refresh / dirty-state / saving-state /
selected-session-disappear paths.

Hardening changes:

- **Service layer** (`worktrace/services/activity_service.py`):
  `batch_update_activity_project` already used a single atomic transaction
  with a rowcount guard. Phase 3B.6.1 verifies that mid-transaction
  exceptions (assignment UPSERT failure, `activity_log` UPDATE failure,
  pre-write SELECT failure) roll back the entire transaction so no partial
  project assignment is left behind. Mixed invalid selections (one valid +
  one deleted / hidden / in-progress / nonexistent) reject all activities
  without modifying the valid one. Duplicate ids are deduped before
  validation. The exact max boundary (100 activities) succeeds; over 100
  rejects. Assignment confidence / source / is_manual match the single-edit
  path (`update_activities_project(manual=True)`). Resource rows
  (`activity_resource`) and session notes (`project_session_note`) are
  unchanged.
- **API layer** (`worktrace/api/timeline_api.py`):
  `batch_update_timeline_activities_project` now catches non-ValueError
  service exceptions (e.g. `sqlite3.OperationalError`, `RuntimeError`) and
  maps them to `operation_failed` so the bridge returns a clear generic
  message without echoing internal details or tracebacks. The error code
  mapping table is unchanged: `invalid_activity_ids` / `activity_not_found`
  / `activity_deleted` → `invalid_selection`; `batch_too_large` →
  `batch_too_large`; `invalid_project` → `invalid_project`;
  `activity_in_progress` → `in_progress`; `activity_hidden` →
  `hidden_activity`; anything else → `operation_failed`.
- **Bridge layer** (`worktrace/webview_ui/bridge.py`): the bridge already
  collapsed unexpected exceptions to `操作失败`. Phase 3B.6.1 verifies the
  error payload contains no traceback / SQL / `window_title` /
  `file_path_hint` / `full_path` / clipboard / note values.
- **Frontend** (`worktrace/webview_ui/app.js` / `index.html` /
  `styles.css`):
  - `batchProjectSaving` is an independent state variable, not aliased to
    `editSaving` / `timeSaving` / `activityTimeSaving` / `sessionSplitSaving`
    / `activitySplitSaving` / `mergeSaving` / `hideSaving` / `deleteSaving`.
  - `setBatchProjectSaving(true)` disables the save button, select-all
    button, clear button, project select, and every batch checkbox; the
    save button text changes to `保存中…`.
  - `saveBatchProject` is guarded by `batchProjectSaving` (prevents
    double-submit), checks `isEditDirty()` before the bridge call (shows
    `请先保存或取消当前编辑`), validates the project selection (shows
    `请选择有效的项目`), and re-derives selected ids from the currently
    rendered shell rows (`querySelectorAll` + `data-batch-activity-id`) so
    stale ids are pruned before the bridge call.
  - `pruneStaleBatchSelection` drops ids that disappeared from the rendered
    activity list and skips in-progress activities; it uses a `^[0-9]+`
    regex so invalid (non-numeric) ids are dropped. It is called from both
    `renderCorrectionShell` and `renderBatchProjectSection` so auto-refresh
    always prunes.
  - The `.then` handler calls `setBatchProjectSaving(false)` before
    branching; the failure branch does **not** clear the selection or call
    `resetBatchProjectState`. The `.catch` handler resets saving and shows
    `操作失败`.
  - The success path clears `selectedBatchActivityIds`, resets
    `batchProjectTargetId`, shows `已批量更新项目`, and refreshes the
    Timeline.
  - `selectTimelineSession` (on switch), `goPrevDay` / `goNextDay` /
    `goToday`, `clearEditPanel`, and `resetCorrectionShellState` all call
    `resetBatchProjectState` so the batch selection never carries over to a
    different session or date.
  - No `localStorage` / `sessionStorage` usage; no external links / CDN /
  Google Fonts; no traceback display; no batch hide / delete / time /
  split / merge UI; no restore / permanent delete / auto-rule / overlap
  handler.

DB schema: **no new schema**. The hardening does not alter any table or
column.

## Phase 3B.6.1 Not Implemented

Phase 3B.6.1 does not implement and does not start:

- Batch note editing;
- Batch hide / batch delete;
- Batch time correction;
- Batch split;
- Batch merge;
- Undo / restore;
- Permanent delete;
- Auto-rule creation;
- Global overlap detection;
- Arbitrary-length merge;
- Multi-activity session whole-hide / whole-delete;
- Any new DB schema;
- Any new batch write type;
- Any React / Vue / Vite / Node dependency;
- Any local HTTP server;
- Any CDN / external JS / CSS / font / Google Fonts usage;
- Any `localStorage` / `sessionStorage` usage;
- Any Tkinter fallback path.

## Phase 3B.7 Implemented Scope

Phase 3B.7 implements the **second batch write capability** in the WebView
Timeline: **batch note overwrite**. Multiple closed activities selected in
the correction shell (Phase 3B.5B shell) can have their `note` field
overwritten to the same value in one operation. This is the **only** batch
write capability introduced in this phase; it is **not** a general batch
editing phase. It is batch note **overwrite** only — batch note append and
batch note merge are explicitly out of scope.

Backend write path:

- Service layer (`worktrace/services/activity_service.py`):
  `batch_update_activity_note(activity_ids, note) -> int`. Validates the
  activity id list (must be a list, dedup to ≥ 2, each item a positive int,
  reject bool, reject > `MAX_BATCH_NOTE_EDIT_ACTIVITIES` (= 100)), validates
  the note (must be `str`, not `None`, length ≤ `BATCH_NOTE_MAX_LENGTH`
  (= 2000); empty string is allowed and is used to batch-clear notes),
  validates every activity (exists, `is_deleted = 0`, `is_hidden = 0`,
  raw DB `end_time IS NOT NULL` i.e. closed — in-progress rejected), then
  performs a single atomic transaction: UPDATEs each activity's `note`
  column to the new value, refreshes `updated_at`, applies a rowcount guard
  (any UPDATE affecting 0 rows raises and rolls back), and returns the
  updated activity count. Only `activity_log.note` and `updated_at` are
  modified — `source` is intentionally **not** changed (unlike the single
  `update_activity_note` which sets `source = 'manual'`). The service does
  not read, concatenate, or return old note values. Any validation or write
  failure rolls back the whole transaction so no partial note write is left
  behind. Service raises stable `ValueError(code)` codes:
  `invalid_activity_ids`, `batch_too_large`, `invalid_note`,
  `note_too_long`, `activity_not_found`, `activity_deleted`,
  `activity_hidden`, `activity_in_progress`, `note_update_failed`.
- API layer (`worktrace/api/timeline_api.py`):
  `batch_update_timeline_activities_note(activity_ids, note) -> dict`
  returns `{"updated_count": n}`. Defines
  `TimelineBatchNoteError(ValueError)` with stable codes:
  `invalid_selection`, `batch_too_large`, `invalid_note`, `note_too_long`,
  `in_progress`, `hidden_activity`, `operation_failed`. Service error codes
  are mapped: `invalid_activity_ids` / `activity_not_found` /
  `activity_deleted` → `invalid_selection`; `batch_too_large` →
  `batch_too_large`; `invalid_note` → `invalid_note`; `note_too_long` →
  `note_too_long`; `activity_in_progress` → `in_progress`;
  `activity_hidden` → `hidden_activity`; anything else →
  `operation_failed`. The API never returns raw rows, raw field values,
  old note values, tracebacks, SQL errors, or internal exception text.
- Bridge layer (`worktrace/webview_ui/bridge.py`):
  `batch_update_timeline_activities_note(activity_ids, note) -> dict`
  returns `{"ok": true, "updated_count": n}` on success and
  `{"ok": false, "error": "<中文错误>"}` on failure. The bridge imports
  only `worktrace.api` / `worktrace.formatters`; it does **not** import
  `services` / `db` / `collector` / `runtime` / `security` / `config`.
  Chinese error message mapping via `_BATCH_NOTE_ERROR_MESSAGES`:
  `invalid_selection` → `请选择至少两个活动`; `batch_too_large` →
  `一次最多修改 100 条活动`; `invalid_note` → `请输入有效备注`;
  `note_too_long` → `备注过长`; `in_progress` →
  `进行中记录暂不支持批量修改`; `hidden_activity` →
  `隐藏记录暂不支持批量修改`; `operation_failed` / unknown → `操作失败`.
  The bridge rejects bool ids at the boundary, rejects non-list ids,
  rejects `None` / non-str note, never returns tracebacks / SQL /
  `window_title` / `file_path_hint` / `full_path` / clipboard / old note
  values / new note content, and falls back to the generic `操作失败`
  message on any unexpected exception.

Frontend (`worktrace/webview_ui/index.html` / `app.js` / `styles.css`):

- The Phase 3B.5B correction shell gains a dedicated `批量备注覆盖`
  section rendered after the `批量项目重分类` section. The section is
  rendered inside the shell (advanced edit layout), not as a new sidebar
  nav item, and not on the simple detail panel.
- The batch note section **reuses** the same `selectedBatchActivityIds`
  selection state as the batch project section — the user checks
  activities once and can then choose to either batch-set the project or
  batch-overwrite the note. No separate selection state is introduced.
- Controls: a `<textarea>` with placeholder
  `输入要覆盖到所选活动的备注（留空将清空所选活动备注）`, a note count
  label `0 / 2000` that updates on input and turns red when the limit is
  exceeded, and a `批量覆盖备注` save button. The save button is disabled
  when fewer than 2 activities are selected, when the note exceeds the
  2000-character limit, or while a batch save is in flight. Saving
  disables the checkboxes, textarea, and button.
- Hint: `仅支持将所选活动的备注覆盖为同一内容；暂不支持追加、合并或保留旧备注。`
  — no append / merge mode toggle is exposed.
- Dirty-state guard: `saveBatchNote` refuses while `isEditDirty()` is
  true with `请先保存或取消当前编辑`; it does **not** clear the detail
  list, the selection, or the note textarea.
- Cross-saving guard: `saveBatchNote` refuses while `batchProjectSaving`
  is true (and vice versa, `saveBatchProject` refuses while
  `batchNoteSaving` is true) so two batch saves cannot compete.
- Save flow: stale selected ids are pruned on every render and re-checked
  against the currently rendered shell rows before the bridge call. On
  success, the selection and note textarea are cleared and the Timeline
  is refreshed (the selected session is preserved when possible; if the
  session regroups or disappears, the shell is safely closed). On
  failure, the selection, note textarea, and detail list are preserved
  and a Chinese error is shown without exposing tracebacks. The `catch`
  path resets `batchNoteSaving` and shows `操作失败`.
- State boundaries: `clearEditPanel`, `resetCorrectionShellState`,
  `closeCorrectionShell`, `selectTimelineSession` (on switch), and date
  navigation (`goPrevDay` / `goNextDay` / `goToday`) all clear the batch
  selection and reset `batchNoteSaving` / the note textarea / the note
  count / the note status. Auto-refresh re-renders the batch rows only
  when the shell is open and not dirty, and prunes stale selected ids
  automatically; it never overwrites the selection or textarea while a
  save is in flight. When the selected session disappears, the shell is
  closed and the selection / note textarea are cleared.
- CSS: the batch note section reuses the existing shell and batch project
  styling; the textarea reuses the existing `.edit-note` styling with a
  `min-height` and `resize: vertical` override. Narrow-viewport rules
  keep the textarea and button from overflowing. No external fonts /
  icons / resources are used. Phase 3B.5A action-group styles, the
  Phase 3B.5B shell layout, and the Phase 3B.6 batch project section are
  untouched.

Privacy / safety:

- The shell activity rows continue to use display-safe fields only (no raw
  `window_title` / `file_path_hint` / `full_path` / clipboard / note
  internals). The batch note save status area never displays tracebacks,
  SQL errors, raw field values, old note values, or the new note content.
- The bridge returns only `ok` / `updated_count` / `error` (a Chinese
  message); no raw rows are returned to the frontend.
- The WebView bridge boundary is unchanged: the bridge imports only
  `worktrace.api` / `worktrace.formatters`.

DB schema: **no new schema**. The batch write reuses the existing
`activity_log.note` and `activity_log.updated_at` columns only.

## Phase 3B.7 Not Implemented

Phase 3B.7 does not implement and does not start:

- Batch note append (concatenating note text onto existing notes);
- Batch note merge (combining multiple notes into one);
- Batch hide / batch delete;
- Batch time correction;
- Batch split;
- Batch merge;
- Undo / restore;
- Permanent delete;
- Auto-rule creation;
- Global overlap detection;
- Arbitrary-length merge;
- Multi-activity session whole-hide / whole-delete;
- Any new DB schema;
- Any new batch write type other than note overwrite;
- Any React / Vue / Vite / Node dependency;
- Any local HTTP server;
- Any CDN / external JS / CSS / font / Google Fonts usage;
- Any `localStorage` / `sessionStorage` usage;
- Any Tkinter fallback path.

## Phase 3B.7.1 Implemented Scope

Phase 3B.7.1 is a **hardening-only** phase for the Phase 3B.7 batch note
overwrite. It introduces **no new features** and **no new batch write
types**. The hardening stabilizes the batch note overwrite across the
service transaction, API error mapping, bridge error convergence, and
frontend stale selection / textarea preservation / auto-refresh /
dirty-state / saving-state / selected-session-disappear paths.

Hardening coverage:

- **Service layer**: verified that `batch_update_activity_note` does NOT
  set `source = 'manual'` (the key semantic difference from the single
  `update_activity_note` path which does set `source = 'manual'`); the
  `source` column remains unchanged after a batch note overwrite. Verified
  that the `note_update_failed` error code is raised on rowcount mismatch
  (race condition). Verified that every selected activity's note equals
  the target note exactly (not concatenated, not prefixed, not
  truncated). Verified that empty string clears the note on every selected
  activity. Verified that `updated_at` is refreshed on every selected
  activity.
- **API layer**: verified the complete service → API error code mapping
  table (every stable `ValueError(code)` maps to a stable
  `TimelineBatchNoteError(code)`): `invalid_activity_ids` /
  `activity_not_found` / `activity_deleted` → `invalid_selection`;
  `batch_too_large` → `batch_too_large`; `invalid_note` → `invalid_note`;
  `note_too_long` → `note_too_long`; `activity_hidden` →
  `hidden_activity`; `activity_in_progress` → `in_progress`;
  `note_update_failed` / unknown → `operation_failed`. Verified that a
  non-`ValueError` service exception collapses to `operation_failed`
  without leaking the exception text. Verified that the API return payload
  contains only `{"updated_count": n}` — no note content, no old/new note
  keys, no raw rows, no exception text.
- **Bridge layer**: verified that error payloads do not contain the note
  content that was sent to the bridge (a user may type sensitive content
  into the note textarea; a validation error must not echo it back).
  Verified that `updated_count` matches the deduplicated selection count.
  Verified that every stable error code produces its exact Chinese
  message. Verified that unknown codes converge to `操作失败`. Verified
  that the success payload contains exactly `{"ok": true, "updated_count":
  n}` and the error payload contains exactly `{"ok": false, "error":
  "<message>"}` — no extra keys that could leak internal data. Verified
  that the bridge rejects overly long notes before calling the API.
- **Frontend**: verified the cross-save guard — `saveBatchNote` checks
  `batchProjectSaving` before proceeding (and vice versa,
  `saveBatchProject` checks `batchNoteSaving`), so two batch saves cannot
  compete. Verified that `setBatchNoteSaving` disables the batch project
  controls (save button / select-all / clear / project select), and
  `setBatchProjectSaving` disables the batch note textarea. Verified that
  `selectTimelineSession`, `goPrevDay`, `goNextDay`, `goToday`, and
  `closeCorrectionShell` all call `resetCorrectionShellState` (which calls
  `resetBatchNoteState`) so the note textarea does not carry over to a
  different session / date / shell state. Verified that
  `resetBatchNoteState` clears the textarea value, resets the count, and
  resets `batchNoteSaving`. Verified that the error handling code does
  not reference `old_note` / `new_note` / `oldNote` / `newNote`
  variables. Verified that the failure path preserves the note textarea
  (does not clear it or call `resetBatchNoteState`). Verified that the
  success path clears both the selection and the note textarea.

DB schema: **no new schema**. No code changes were made to the service /
API / bridge / frontend implementation — the Phase 3B.7 foundation was
already solid; this phase adds explicit hardening tests and documentation
to guard against regressions.

## Phase 3B.7.1 Not Implemented

Phase 3B.7.1 does not implement and does not start:

- Batch note append (concatenating note text onto existing notes);
- Batch note merge (combining multiple notes into one);
- Batch hide / batch delete;
- Batch time correction;
- Batch split;
- Batch merge;
- Undo / restore;
- Permanent delete;
- Auto-rule creation;
- Global overlap detection;
- Arbitrary-length merge;
- Multi-activity session whole-hide / whole-delete;
- Any new DB schema;
- Any new batch write type;
- Any new feature or UI control;
- Any React / Vue / Vite / Node dependency;
- Any local HTTP server;
- Any CDN / external JS / CSS / font / Google Fonts usage;
- Any `localStorage` / `sessionStorage` usage;
- Any Tkinter fallback path.

## Phase 3B.8 Implemented Scope

Phase 3B.8 implements the **single activity restore foundation** in the
WebView Timeline. A single hidden activity (`is_hidden = 1`) or soft-deleted
activity (`is_deleted = 1`) can be restored to visible + not-deleted in one
operation. This is a **single-activity restore only** phase — batch restore,
undo stack, and permanent delete are explicitly out of scope.

### What restore modifies

The restore operation is a single atomic UPDATE with a rowcount guard. It
modifies **only**:

- `activity_log.is_hidden` → `0`;
- `activity_log.is_deleted` → `0`;
- `activity_log.updated_at` → refreshed to `now()`.

### What restore does not modify

- `start_time`, `end_time`, `duration_seconds`;
- `project_id`, `note`, `status`, `source`;
- `activity_resource` rows;
- `activity_project_assignment` rows;
- `project_session_note` rows;
- The row is never physically deleted.

### Service layer

`worktrace.services.activity_service.restore_activity(activity_id)` performs
a single fetch + single UPDATE. Input validation rejects `bool`,
non-positive, and non-int ids. The activity must exist, must be hidden or
deleted, and must be closed (raw `end_time IS NOT NULL`). A rowcount guard
ensures exactly 1 row is affected; a 0-row UPDATE (race condition) raises
`ValueError("restore_failed")`.

`worktrace.services.activity_service.list_restorable_activities_for_date(date)`
returns a display-safe recovery list of hidden / deleted closed activities
for the given date, sorted by `start_time`. Only display-safe fields are
returned (no raw `window_title`, `file_path_hint`, `full_path`, `clipboard`,
or `note`). In-progress hidden/deleted activities are excluded.

### API layer

`worktrace.api.timeline_api.restore_timeline_activity(activity_id)` validates
the id and delegates to the service. Service `ValueError` codes are mapped to
stable `TimelineRestoreActivityError` codes:

- `invalid_activity_id` → `invalid_activity`
- `activity_not_found` → `not_found`
- `activity_not_restorable` → `not_restorable`
- `activity_in_progress` → `in_progress`
- `restore_failed` or any unexpected exception → `operation_failed`

`worktrace.api.timeline_api.get_timeline_restorable_activities(date)` returns
`{"activities": [...]}` with display-safe fields only. Invalid dates raise
`TimelineRestoreActivityError("invalid_date")`.

### Bridge layer

`WebViewBridge.restore_timeline_activity(activity_id)` returns
`{"ok": true, "activity_id": int}` on success or
`{"ok": false, "error": "<chinese message>"}` on failure. Known error codes
map to clear Chinese messages; unknown codes collapse to `恢复失败`.

`WebViewBridge.get_timeline_restorable_activities(date)` returns
`{"ok": true, "activities": [...]}` on success or
`{"ok": false, "error": "<chinese message>", "activities": []}` on failure.
The recovery list error path collapses to `加载可恢复记录失败` (except
`invalid_date` → `日期无效`).

### Frontend

The Phase 3B.5B correction shell gains a dedicated `可恢复记录` section
after the batch note section. The section hint states:
"仅支持恢复单条隐藏或软删除记录；暂不支持批量恢复、撤销栈或永久删除。"

The section loads the recovery list for the current Timeline date when the
shell opens. Each row shows time range, duration, app/resource/project,
and a restore-state badge (`已隐藏` / `已删除` / `已隐藏且已删除`). A
single `恢复` button per row calls `restore_timeline_activity`. On success,
the Timeline is refreshed and the recovery list is reloaded. On failure,
the list is preserved for retry. The `restoreSaving` state is independent
from `batchProjectSaving` / `batchNoteSaving` and all other edit saving
states. `clearEditPanel` and `resetCorrectionShellState` both call
`resetRestoreState` so no stale list / saving flag leaks across sessions.

### CSS

The restore section reuses the existing shell styling conventions. The
`.correction-shell-restore-list:empty::after` rule shows `暂无可恢复记录`
when the list is empty. Restore-state badges use distinct colors:
`.is-deleted` (red), `.is-hidden-deleted` (purple). The `.restore-saving`
class dims the in-flight row.

## Phase 3B.8 Not Implemented

Phase 3B.8 does not implement and does not start:

- Batch restore (restoring multiple activities at once);
- Restore all;
- Undo stack (multi-step undo / redo);
- Permanent delete (physically deleting a row);
- Batch hide / batch delete;
- Batch time correction;
- Batch split;
- Batch merge;
- Auto-rule creation;
- Global overlap detection;
- Arbitrary-length merge;
- Multi-activity session whole-hide / whole-delete;
- Any new DB schema;
- Any new batch write type;
- Any React / Vue / Vite / Node dependency;
- Any local HTTP server;
- Any CDN / external JS / CSS / font / Google Fonts usage;
- Any `localStorage` / `sessionStorage` usage;
- Any Tkinter fallback path.

## Phase 3B.8.1 Implemented Scope

Phase 3B.8.1 is a **hardening-only** phase for the Phase 3B.8 single activity
restore foundation. No new features, no new restore/delete/batch types, no
new DB schema, and no new UI controls are introduced. The hardening
strengthens the restore path across service rowcount/rollback,
not-restorable/in-progress, hidden+deleted, recovery list display-safe,
API error mapping, bridge error convergence, frontend dirty-state /
saving-state / date-switch / session-switch / auto-refresh /
selected-session-disappear paths.

### Service layer hardening

- `restore_activity` write exception (e.g. `sqlite3.OperationalError`)
  propagates and the transaction rolls back so no partial write survives
  (the activity remains hidden/deleted).
- The `restore_activity` rowcount guard continues to reject a 0-row
  UPDATE (race condition: the activity was restored or re-opened between
  validation and write) as `ValueError("restore_failed")`.
- `restore_activity` is idempotent in rejection: an already-restored row
  (normal activity) is rejected as `activity_not_restorable` — restore is
  never a silent no-op.
- `list_restorable_activities_for_date` is sorted by `start_time ASC, id ASC`
  so two activities with the same start time have a stable order (id
  tiebreaker).
- `list_restorable_activities_for_date` read path performs no write and does
  not refresh `updated_at` for any activity.
- Restore refreshes `updated_at` to `now()` (verified by a test that sleeps
  to cross the SQLite second boundary).

### API layer hardening

- `restore_timeline_activity` maps non-ValueError service exceptions (e.g.
  `RuntimeError`) to `operation_failed` so the bridge never receives an
  unhandled exception type.
- `get_timeline_restorable_activities` also collapses non-ValueError
  service exceptions to `operation_failed`.
- API error messages do not leak the service exception class name or
  internal detail (e.g. `OSError`, "disk full", raw SQL) — only the
  stable `.code` is surfaced.
- The API return payload never includes raw rows, exception text,
  `window_title`, `file_path_hint`, `full_path`, `clipboard`, or `note`.

### Bridge layer hardening

- The `_RESTORE_ERROR_MESSAGES` dict maps every stable API code to a
  clear Chinese message:
  - `invalid_activity` → `请选择有效的活动`
  - `not_found` → `活动不存在`
  - `not_restorable` → `该活动无需恢复`
  - `in_progress` → `进行中记录暂不支持恢复`
  - `invalid_date` → `日期无效`
  - `operation_failed` → `恢复失败`
- Unknown error codes and unexpected exceptions collapse to `恢复失败`
  (restore) / `加载可恢复记录失败` (recovery list) without echoing
  tracebacks, SQL, exception class names, or raw fields.
- The bridge continues to import only `worktrace.api` — it does not
  directly import `services` / `db` / `collector` / `runtime` / `security` /
  `config`.

### Frontend hardening

- **Stale-row guard**: `saveActivityRestore` queries the DOM for a
  `.correction-shell-restore-row[data-activity-id="..."]` matching the
  clicked activity before calling the bridge. If the row is no longer
  present (e.g. the list was reloaded by an auto-refresh and the activity
  is gone), a safe message `该活动已不在可恢复列表中，请刷新后重试` is
  shown and the bridge is NOT called. The stale-row guard runs before the
  `isEditDirty()` check and does not change the selected session.
- **Auto-refresh reload guard**: the auto-refresh path that re-renders the
  correction shell (and thus the restore section) is guarded by a
  four-layer chain:
  1. `correctionShellOpen` — the shell must be open;
  2. `correctionShellSessionId === found.session_id` — the session must
     match;
  3. `!isEditDirty()` — no unsaved edits;
  4. `restoreSaving` — `renderRestoreSection` early-returns when a restore
     save is in flight so the in-flight save's success/failure handler
     completes the reload itself.
- The `restoreSaving` / `restoreSavingActivityId` state remains
  independent from `batchProjectSaving` / `batchNoteSaving` / `editSaving` /
  `timeSaving` / `activityTimeSaving` / `sessionSplitSaving` /
  `activitySplitSaving` / `mergeSaving` / `hideSaving` / `deleteSaving` and
  all correction shell state.
- `clearEditPanel` and `resetCorrectionShellState` continue to call
  `resetRestoreState` so no stale list / saving flag leaks across sessions,
  dates, or shell close.
- Dynamic values in the restore list continue to be escaped via
  `escapeHtml`; no `localStorage` / `sessionStorage`, external links,
  tracebacks, or raw field display.

### What Phase 3B.8.1 does not change

- `restore_activity` still modifies only `is_hidden`, `is_deleted`,
  `updated_at` — `start_time`, `end_time`, `duration_seconds`,
  `project_id`, `note`, `status`, `source`, resource rows, assignment
  rows, and `project_session_note` are unchanged.
- The row is never physically deleted.
- No new DB schema.
- No batch restore, restore all, undo stack, or permanent delete.

## Phase 3B.8.1 Not Implemented

Phase 3B.8.1 does not implement and does not start:

- Batch restore (restoring multiple activities at once);
- Restore all;
- Undo stack (multi-step undo / redo);
- Permanent delete (physically deleting a row);
- Batch hide / batch delete;
- Batch time correction;
- Batch split;
- Batch merge;
- Auto-rule creation;
- Global overlap detection;
- Arbitrary-length merge;
- Multi-activity session whole-hide / whole-delete;
- Any new DB schema;
- Any new batch write type;
- Any React / Vue / Vite / Node dependency;
- Any local HTTP server;
- Any CDN / external JS / CSS / font / Google Fonts usage;
- Any `localStorage` / `sessionStorage` usage;
- Any Tkinter fallback path.

## Phase 3B.9 Implemented Scope

Phase 3B.9 is a **consolidation-only** phase for the Timeline correction
shell. It does NOT add any backend write capability, bridge / API / service
method, DB schema, or new correction action. It only reorganizes the
shell's internal UI structure, state, copy, render helpers, and CSS so the
accumulated Phase 3B.5B / 3B.6 / 3B.7 / 3B.8 functionality reads as a
single, stable, maintainable shell.

The consolidation covers:

- **Shell cards.** The correction shell is now organized into unified
  cards with stable IDs:
  `correction-shell-context-card`,
  `correction-shell-activity-card`,
  `correction-shell-single-action-card`,
  `correction-shell-batch-action-card`,
  `correction-shell-restore-card`, and
  `correction-shell-not-implemented-card`. Each card carries a
  `.correction-shell-card-header` and an optional
  `.correction-shell-card-hint`. All existing IDs from prior phases
  (e.g. `correction-shell-context`, `correction-shell-activities`,
  `correction-shell-actions`, `correction-shell-batch-project-section`,
  `correction-shell-batch-note-section`,
  `correction-shell-restore-section`) are preserved so prior-phase tests
  keep passing.
- **Single actions / batch actions / recovery list grouping.** Single
  activity actions (edit time / split / merge / hide / delete) live in
  the single-action card as guidance; batch project reassignment and
  batch note overwrite live together in the batch-action card and share
  the same `selectedBatchActivityIds` selection; the recovery list lives
  in the restore card. A dedicated not-implemented card explicitly lists
  the unsupported capabilities (batch hide / delete / restore, restore
  all, undo stack, permanent delete, batch time / split / merge, note
  append / merge, auto-rule, global overlap detection).
- **Shared selection.** Batch project and batch note continue to share a
  single `selectedBatchActivityIds` source of truth; the selected count
  is derived from one place; select-all / clear affect only eligible
  current shell activities; auto-refresh prunes disappeared / ineligible
  ids; shell close / date switch / session switch clear the selection.
- **Shared status / empty / loading / disabled semantics.** A unified
  `resetCorrectionActionStatus()` helper clears every shell status area
  (shell / batch project / batch note / restore) on open so stale
  messages do not linger. The unified Chinese copy is preserved:
  `请先保存或取消当前编辑`, `请等待当前操作完成`, `已批量更新项目`,
  `已批量更新备注`, `已恢复`, `操作失败`, `恢复失败`,
  `暂无可恢复记录`.
- **Cross-save guard.** A unified `isAnyCorrectionWriteSaving()` helper
  returns true when any correction-shell write (batch project / batch
  note / single restore) is in flight. `saveBatchProject` refuses when
  batch note or restore is saving; `saveBatchNote` refuses when restore
  is saving; `saveActivityRestore` refuses when batch project or batch
  note is saving. Every cross-save refusal uses the stable
  `请等待当前操作完成` message and does NOT call the bridge.
- **Display-safe rendering helper.** A unified `safeText(value, fallback)`
  helper returns the fallback for null / undefined / empty values and
  stringifies non-empty values. `renderCorrectionShell` and
  `renderRestorableActivities` pass every dynamic value through
  `safeText` followed by `escapeHtml` so the shell never renders
  `undefined` / `null`. The shell never reads raw `window_title`,
  `file_path_hint`, `full_path`, `clipboard`, note internals,
  traceback, SQL, or exception text.
- **CSS consolidation.** A unified `.correction-shell-card` style
  (with `.correction-shell-card-header`, `.correction-shell-card-hint`,
  `.correction-shell-card[hidden]`) replaces the per-section card chrome
  so context / activity / single-action / batch / restore / not-implemented
  cards share one visual hierarchy. The existing
  `.correction-shell[hidden] { display: none }` rule and the
  `.detail-item-highlight` rule are preserved. Narrow-viewport rules keep
  the cards stable (no overflow, rows wrap, padding tightens).
- **No raw fields.** The shell, the activity rows, the context summary,
  and the recovery list only use display-safe fields (`activity_id`,
  time range, `resource_name`, `app_name`, `resource_type`,
  `project_name`, `duration`, `is_in_progress`, `restore_state`). Raw
  `window_title` / `file_path_hint` / `full_path` / clipboard / note
  internals / traceback / SQL / exception text are never read or
  displayed.

## Phase 3B.9 Not Implemented

Phase 3B.9 does not implement and does not start:

- Any new backend write capability;
- Any new bridge / API / service method;
- Any new DB schema;
- Any new correction action;
- Batch hide;
- Batch delete;
- Batch restore;
- Restore all;
- Undo stack;
- Permanent delete;
- Batch time correction;
- Batch split;
- Batch merge;
- Batch note append;
- Batch note merge;
- Auto-rule creation;
- Global overlap detection;
- Arbitrary-length merge;
- Multi-activity session whole-hide / whole-delete;
- Any React / Vue / Vite / Node dependency;
- Any local HTTP server;
- Any CDN / external JS / CSS / font / Google Fonts usage;
- Any `localStorage` / `sessionStorage` usage;
- Any Tkinter fallback path.

## Phase 3B.9.1 Implemented Scope

Phase 3B.9.1 is a **hardening-only** phase for the Timeline correction shell
consolidation. It does NOT add any backend write capability, bridge / API /
service method, DB schema, or new correction action. It only hardens the
Phase 3B.9 consolidation so the shell card structure, helpers, cross-save
guard, reset semantics, display-safe rendering, and CSS remain stable under
complex UI state transitions.

The hardening covers:

- **Cross-save guard message consistency.** `saveBatchNote` now uses the
  unified `请等待当前操作完成` message for BOTH `batchProjectSaving` and
  `restoreSaving` (previously `batchProjectSaving` used `操作失败`). The
  two checks are consolidated into a single
  `if (batchProjectSaving || restoreSaving)` guard that matches the
  structure of `saveBatchProject` and `saveActivityRestore`.
- **Auto-refresh saving guard.** The auto-refresh re-render path now checks
  `isAnyCorrectionWriteSaving()` before calling `renderCorrectionShell`. When
  any correction-shell write (batch project / batch note / single restore)
  is in flight, the shell is NOT re-rendered, so the saving state, selection,
  textarea, and status messages are not overwritten mid-save.
- **Render helper status guard.** `renderBatchProjectSection` and
  `renderBatchNoteSection` no longer clear their status area
  (`showBatchProjectStatus("", false)` / `showBatchNoteStatus("", false)`)
  while a save is in flight. The save success / failure handler owns the
  status during saving; an auto-refresh re-render must not wipe a just-shown
  error or success message.
- **Card structure regression lock.** All six correction shell cards
  (context / activity / single-action / batch-action / restore /
  not-implemented) and all existing JS-dependent IDs are confirmed stable.
- **Reset helper contracts.** `resetCorrectionShellState` continues to call
  `resetBatchProjectState`, `resetBatchNoteState`, and `resetRestoreState`.
  Close / date switch / session switch / selected session disappear all
  call `resetCorrectionShellState`. `closeCorrectionShell` preserves
  `selectedSessionId` so the user returns to the same session context.
- **Dirty guard ordering.** In all three consolidated write paths
  (`saveBatchProject`, `saveBatchNote`, `saveActivityRestore`), the dirty
  guard (`isEditDirty`) comes BEFORE the cross-save guard, which comes
  before any bridge call.
- **Cross-save guard no-bridge.** None of the three cross-save guard paths
  call `callBridge`; they only show a status and return. They do not clear
  selection, textarea, or restore list.
- **Display-safe rendering.** `safeText` + `escapeHtml` continue to cover
  every dynamic value in `renderCorrectionShell` and
  `renderRestorableActivities`. No raw `window_title` / `file_path_hint` /
  `full_path` / clipboard / note internals / traceback / SQL / exception
  text is read or displayed.
- **CSS state hardening.** `.correction-shell[hidden] { display: none }`,
  the unified `.correction-shell-card` / `-card-header` / `-card-hint` /
  `-status` classes, and the `.detail-item-highlight` / `.shell-target`
  highlight rules are all preserved. No external CSS / font / CDN
  references are introduced.

## Phase 3B.9.1 Not Implemented

Phase 3B.9.1 does not implement and does not start:

- Any new backend write capability;
- Any new bridge / API / service method;
- Any new DB schema;
- Any new correction action;
- Batch hide;
- Batch delete;
- Batch restore;
- Restore all;
- Undo stack;
- Permanent delete;
- Batch time correction;
- Batch split;
- Batch merge;
- Batch note append;
- Batch note merge;
- Auto-rule creation;
- Global overlap detection;
- Arbitrary-length merge;
- Multi-activity session whole-hide / whole-delete;
- Any React / Vue / Vite / Node dependency;
- Any local HTTP server;
- Any CDN / external JS / CSS / font / Google Fonts usage;
- Any `localStorage` / `sessionStorage` usage;
- Any Tkinter fallback path.

## Phase 3C Implemented Scope

Phase 3C is the **Timeline UI release stabilization** phase. It is a
stabilization-only phase, not a feature expansion phase. The goal is to
push the Timeline / Time Details page from "feature-complete" to
"release-ready" without adding any new backend write capability,
bridge / API / service method, DB schema, correction action, or UI
control.

Stabilization scope:

1. **Unified Timeline status semantics.** Added additive unified
   status helpers in `worktrace/webview_ui/app.js`:
   - `STATUS_TYPE_CLASS` map (info / success / error / loading / empty);
   - `statusClassFor(type)`;
   - `applyStatusType(el, type)`;
   - `setTimelineStatus(message, type)` — delegates to the existing
     `#timeline-error` banner and `#timeline-loading` indicator;
   - `setDetailStatus(message, type)` — delegates to the existing
     `#timeline-details-header` text;
   - `setEditStatus(message, type)` — delegates to `showEditStatus`;
   - `setCorrectionStatus(message, type)` — delegates to
     `setCorrectionShellStatus`.

   These helpers are **additive**: the existing per-area helpers
   (`showEditStatus`, `showTimeStatus`, `setCorrectionShellStatus`,
   `clearTimelineError`, `setTimelineLoading`, `showTimelineError`)
   remain unchanged and continue to own their DOM elements. The
   unified helpers centralize the status-type vocabulary so future
   code and tests can rely on a single contract.

2. **Unified status-type CSS classes.** Added three additive CSS
   classes in `worktrace/webview_ui/styles.css`:
   - `.edit-status-info` (blue);
   - `.edit-status-loading` (slate);
   - `.edit-status-empty` (light slate).

   The existing `.edit-status-error` / `.edit-status-success` rules
   remain the primary error / success styles; the new classes extend
   the vocabulary for info / loading / empty states.

3. **Display-safe hardening — `err.message` leak closure.** Closed
   four `err.message` leaks in `app.js` catch blocks so raw exception
   text never reaches the UI:
   - `loadTimeline().catch()` now uses the stable fallback
     `"加载时间详情失败，请稍后重试。"` instead of `err.message`;
   - `refreshAll()` status / overview / recent catch blocks now use
     stable Chinese fallback strings
     (`"无法连接采集器状态，请稍后重试。"` /
     `"加载今日概览失败，请稍后重试。"` /
     `"加载最近活动失败，请稍后重试。"`) instead of `err.message`,
     and still re-throw the original error so the existing
     `refreshAll` chain semantics are unchanged.

   No `err.message` (or `err.toString()`) reference now reaches a
   status / error DOM element in the Timeline code path.

4. **No new backend write capability.** `bridge.py`,
   `timeline_api.py`, `timeline_service.py`, `activity_service.py`,
   and `schema.sql` are unchanged in Phase 3C. The locked bridge
   method set (21 methods asserted by
   `test_bridge_no_new_methods_for_phase_3b9_1`) is preserved. No
   new API method, service method, DB column, DB table, DB index, or
   DB trigger is introduced.

5. **No new UI control or correction action.** No new sidebar nav
   item, no new top-level page, no new action button, no new
   destructive-action UI, no new card. The correction shell card
   structure (context / activity / single-action / batch-action /
   restore / not-implemented) is preserved.

6. **No DOM contract change.** All existing JS-dependent IDs, CSS
   classes, function names, and Chinese status / button / copy
   strings asserted by `tests/test_webview_resources.py` and the
   Phase 3B.9 / 3B.9.1 test suite are preserved. The unified
   helpers do not rename or relocate any existing DOM element.

7. **Display-safe rendering audit re-confirmed.** The Timeline list,
   detail panel, edit panel, and correction shell still render only
   display-safe fields. The forbidden-field set
   (`window_title` / `file_path_hint` / `full_path` / `clipboard` /
   note internals / SQL / traceback / raw exception text) is still
   absent from the frontend resources and from the bridge return
   values. The four `err.message` leak closures above close the
   last known exception-text leak surface in the Timeline code path.

8. **CSS cleanup is additive.** No existing CSS rule was removed or
   renamed. The three new classes share the same `.edit-status-*`
   prefix family so they participate in the existing status-element
   cascade without colliding with the Phase 3B.1+ card / section
   styles.

9. **Default WebView entry preserved.** `python -m worktrace.main`
   (and the packaged `WorkTrace.exe`) still start the WebView UI
   directly. The Overview, Timeline, and Time Details default
   WebView entries are unchanged. No Tkinter fallback path was
   introduced.

10. **Release validation checklist updated.**
    `docs/release-validation.md` now includes a Phase 3C Validation
    section with the stabilization acceptance items and the release
    blockers list.

## Phase 3C Not Implemented

Phase 3C does not implement and does not start:

- Any new backend write capability;
- Any new bridge / API / service method;
- Any new DB schema;
- Any new correction action;
- Batch hide;
- Batch delete;
- Batch restore;
- Restore all;
- Undo stack;
- Permanent delete;
- Batch time correction;
- Batch split;
- Batch merge;
- Batch note append;
- Batch note merge;
- Auto-rule creation;
- Global overlap detection;
- Arbitrary-length merge;
- Multi-activity session whole-hide / whole-delete;
- Statistics / Export migration to WebView;
- Project Rules migration to WebView;
- Settings / Privacy migration to WebView;
- Any React / Vue / Vite / Node dependency;
- Any local HTTP server;
- Any CDN / external JS / CSS / font / Google Fonts usage;
- Any `localStorage` / `sessionStorage` usage;
- Any Tkinter fallback path;
- Any removal of an existing feature, bridge call, or test.

## Phase 3C.1 Implemented Scope

Phase 3C.1 is the **Timeline UI release hardening / regression** phase. It
is a **hardening-only / regression-only** phase, not a feature expansion
phase. The goal is to lock the Timeline / Time Details page as
release-ready by hardening the Phase 3C status helpers, closing the last
raw-exception leak surface, unifying all Timeline catch-path fallback
strings to a stable short Chinese vocabulary, and adding 43 regression
tests — without adding any new backend write capability, bridge / API /
service method, DB schema, correction action, or UI control.

Hardening scope:

1. **Status helper hardening — `applyStatusType` class preservation.**
   `worktrace/webview_ui/app.js` `applyStatusType(el, type)` previously
   did `el.className = "edit-status " + statusClassFor(type)`, which
   would wipe any structural class the element already had (for example
   `correction-shell-status`). Phase 3C.1 introduces a whitelisted
   `STATUS_TYPE_CLASS_VALUES` array
   (`edit-status-info` / `edit-status-success` / `edit-status-error` /
   `edit-status-loading` / `edit-status-empty`) and rewrites
   `applyStatusType` to filter only those whitelisted classes from the
   existing class list, preserve every other class, ensure the
   `edit-status` base class is present, then push the single
   `statusClassFor(type)` result. Unknown types still fall through to
   the safe `statusClassFor` default (`edit-status-info`). No user
   input is ever spliced into a class name.

2. **Status helper hardening — `statusClassFor` safe default.**
   `statusClassFor(type)` returns `STATUS_TYPE_CLASS[type]` with a
   `|| "edit-status-info"` fallback, so an unknown / missing type never
   throws a JS exception and never produces an `undefined` class name.

3. **Raw exception leak closure — `saveEdit` `Promise.allSettled`
   rejection handler.** The `saveEdit` flow uses `Promise.allSettled`
   to fan out project / note / time / split / merge / hide / delete
   saves. The rejection handler previously read
   `results[i].reason && results[i].reason.message ? ... : "保存失败"`,
   which could surface a raw pywebview exception message. Phase 3C.1
   replaces that with the stable `保存失败` fallback so internal
   exception details never reach the UI. This was the last known
   raw-exception-text leak surface in the Timeline code path.

4. **Stable short Chinese fallback vocabulary.** Phase 3C used longer
   strings (`加载时间详情失败，请稍后重试。` /
   `无法连接采集器状态，请稍后重试。` /
   `加载今日概览失败，请稍后重试。` /
   `加载最近活动失败，请稍后重试。` /
   `刷新时间详情失败，请稍后重试。`). Phase 3C.1 unifies all seven
   Timeline catch-path fallback strings to the stable short vocabulary:
   - `loadTimeline().catch()` → `加载时间线失败`;
   - `refreshAll()` status / overview / recent catch blocks → `刷新失败`;
   - `refreshAll()` timeline refresh catch → `刷新失败`;
   - `refreshTimelineAfterEdit().catch()` → `刷新失败`;
   - `refreshTimeline().catch()` → `刷新失败`;
   - `saveEdit` rejection → `保存失败`.
   The vocabulary (`加载时间线失败` / `刷新失败` / `加载详情失败` /
   `保存失败` / `操作失败` / `恢复失败`) is locked by the Phase 3C.1
   regression tests.

5. **No new backend write capability.** `bridge.py`,
   `timeline_api.py`, `timeline_service.py`, `activity_service.py`,
   and `schema.sql` are unchanged in Phase 3C.1. The locked bridge
   method set (21 methods asserted by
   `test_bridge_no_new_methods_for_phase_3b9_1` and re-asserted by
   `test_bridge_no_new_methods_for_phase_3c1`) is preserved. No
   new API method, service method, DB column, DB table, DB index, or
   DB trigger is introduced.

6. **No new UI control or correction action.** No new sidebar nav
   item, no new top-level page, no new action button, no new
   destructive-action UI, no new card. The correction shell card
   structure (context / activity / single-action / batch-action /
   restore / not-implemented) is preserved.

7. **No DOM contract change.** All existing JS-dependent IDs, CSS
   classes, function names, and Chinese status / button / copy
   strings asserted by `tests/test_webview_resources.py` and the
   prior-phase test suites are preserved. The hardened
   `applyStatusType` does not rename or relocate any existing DOM
   element.

8. **Display-safe rendering audit re-confirmed.** The Timeline list,
   detail panel, edit panel, and correction shell still render only
   display-safe fields. The forbidden-field set
   (`window_title` / `file_path_hint` / `full_path` / clipboard /
   note internals / SQL / traceback / raw exception text) is still
   absent from the frontend resources and from the bridge return
   values. The `saveEdit` `.reason.message` closure above closes the
   last known exception-text leak surface in the Timeline code path.
   `escapeHtml` / `safeText` / `textContent` are still the only
   dynamic-render primitives.

9. **Auto-refresh dirty / saving guards re-confirmed.** The
   `refreshAll` / `refreshTimeline` / `refreshTimelineAfterEdit`
   paths still respect the `isEditDirty()` dirty guard and the
   `isAnyCorrectionWriteSaving()` cross-save guard. A dirty edit
   input, a saving batch project / batch note / restore write, a
   batch selection, a batch note textarea, and a restore list are
   never overwritten by an auto-refresh tick. Date switch and
   session switch still clear shell-only state and reset saving
   flags. The selected-session-disappear path still safely closes
   the shell / clears the detail without a JS exception.

10. **CSS state hardening re-confirmed.** `styles.css` still defines
    the complete status class family
    (`.edit-status-info` / `.edit-status-success` / `.edit-status-error` /
    `.edit-status-loading` / `.edit-status-empty`), the disabled /
    saving button styles, `.correction-shell[hidden] { display: none; }`,
    and the transient highlight CSS. No external CSS / font / CDN
    reference is introduced. No `localStorage` / `sessionStorage`
    reference is introduced.

11. **Default WebView entry preserved.** `python -m worktrace.main`
    (and the packaged `WorkTrace.exe`) still start the WebView UI
    directly. The Overview, Timeline, and Time Details default
    WebView entries are unchanged. No Tkinter fallback path was
    introduced.

12. **Release validation checklist updated.**
    `docs/release-validation.md` now includes a Phase 3C.1 Validation
    section with the hardening acceptance items and the release
    blockers list.

## Phase 3C.1 Not Implemented

Phase 3C.1 does not implement and does not start:

- Any new backend write capability;
- Any new bridge / API / service method;
- Any new DB schema;
- Any new correction action;
- Batch hide;
- Batch delete;
- Batch restore;
- Restore all;
- Undo stack;
- Permanent delete;
- Batch time correction;
- Batch split;
- Batch merge;
- Batch note append;
- Batch note merge;
- Auto-rule creation;
- Global overlap detection;
- Arbitrary-length merge;
- Multi-activity session whole-hide / whole-delete;
- Statistics / Export migration to WebView;
- Project Rules migration to WebView;
- Settings / Privacy migration to WebView;
- Any React / Vue / Vite / Node dependency;
- Any local HTTP server;
- Any CDN / external JS / CSS / font / Google Fonts usage;
- Any `localStorage` / `sessionStorage` usage;
- Any Tkinter fallback path;
- Any removal of an existing feature, bridge call, or test.

## Phase 4A Implemented Scope

Phase 4A is the **Statistics / Export read-only WebView migration
foundation**. It migrates the Statistics / Export page from the legacy
Tkinter placeholder to a read-only WebView page. The page shows a
statistics summary, grouped tables, and an export preview, but does not
perform any export write action.

Implemented in Phase 4A:

- **WebView navigation entry**: the sidebar still lists `统计与导出`; the
  page section `#page-statistics` is now a real migrated page (no longer
  the `WebView 迁移中` placeholder).
- **Read-only page header**: the header says `统计 / 导出` with the
  subtitle `本阶段仅提供只读统计和导出预览，暂不写入文件。`.
- **Date range controls**: `statistics-date-from` / `statistics-date-to`
  date inputs, a `加载统计` load button, and quick-range buttons
  (`今天` / `最近 7 天` / `本月`). The page lazy-loads the summary on
  first navigation; the default range is today.
- **Summary cards**: four cards show total duration, activity count,
  project count, and app count.
- **Grouped tables**: three tables show `按项目` / `按应用` / `按状态`
  breakdowns. Each row has a display name, duration, activity count, and
  percentage. Each table has an empty-state line `暂无统计数据`.
- **Export preview**: a card shows the current range, included activity
  count, included duration, and available formats (`csv`, `timesheet`).
  The export action button is disabled and says
  `导出动作将在后续阶段开放`. A hint explicitly states the page does
  not write CSV / Excel / PDF / timesheet files, does not open a save
  dialog, does not open a folder, and does not auto-submit a timesheet.
- **Read-only service**: `statistics_service.get_statistics_export_summary`
  reads closed activities via `timeline_service.get_report_activity_rows`
  (which already excludes `is_deleted = 1` and, with `include_hidden=False`,
  excludes `is_hidden = 1`). In-progress activities (`end_time IS NULL`)
  are excluded; Phase 4A intentionally does NOT project live time (unlike
  the legacy Tkinter page) so the read-only preview is stable. The
  inclusive date span is capped at `STATISTICS_SUMMARY_MAX_RANGE_DAYS`
  (31 days). The payload is display-safe: it contains only aggregated
  numbers and display names (project name, app name, status label). Raw
  `window_title`, `file_path_hint`, `full_path`, `clipboard`, `note`,
  SQL, and tracebacks are never surfaced.
- **Read-only API**: `statistics_api.get_statistics_export_summary`
  validates the date range and raises `StatisticsSummaryError` with
  stable codes (`invalid_date` / `invalid_range` / `range_too_large` /
  `operation_failed`). Unexpected service exceptions collapse to
  `operation_failed` so internal details never reach the bridge.
- **Read-only bridge**: `WebViewBridge.get_statistics_export_summary`
  calls the API, maps `StatisticsSummaryError` codes to stable Chinese
  messages (`请选择有效日期` / `请选择有效日期范围` / `日期范围过大` /
  `加载统计失败`), and returns `{"ok": true, "summary": {...}}` on
  success or `{"ok": false, "error": "<chinese>", "summary": null}` on
  failure. The bridge payload includes pre-formatted duration strings so
  the frontend does not need a second bridge round-trip. Unexpected
  exceptions collapse to `加载统计失败` without echoing tracebacks, SQL,
  raw exception text, `window_title`, `file_path_hint`, `full_path`,
  `clipboard`, or `note`.
- **CSS**: the page uses the existing WebView visual system (white cards,
  slate borders, tabular-numeric alignment). Summary cards wrap to 2 / 1
  columns on narrow windows; grouped tables stack on narrow windows;
  long names truncate with ellipsis; date controls wrap. The disabled
  export action button uses `cursor: not-allowed`.
- **Tests**: `tests/test_statistics_api_summary.py` covers the
  service / API read-only contract (aggregation, hidden / deleted / in-
  progress exclusion, date range validation, no DB writes, no raw
  fields). `tests/test_webview_bridge_statistics.py` covers the bridge
  read-only contract (success, error code mapping, unexpected-exception
  collapse, no raw fields, no export write method, bridge import
  boundary). `tests/test_webview_resources.py` adds Phase 4A
  frontend / CSS / boundary / doc regression locks.

## Phase 4A Not Implemented

Phase 4A does not implement and does not start:

- Any export write action;
- Any CSV / Excel / PDF / timesheet file creation;
- Any save file dialog;
- Any folder opening;
- Any export write bridge / API / service method;
- Any DB schema change;
- Any DB write;
- Any live-time projection (the legacy Tkinter Statistics page projects
  the live snapshot via `include_live=True`; Phase 4A intentionally does
  not, so the read-only preview is stable);
- Any Project Rules migration to WebView;
- Any Settings / Privacy migration to WebView;
- Any removal of the legacy Tkinter / CustomTkinter UI code;
- Any Tkinter fallback path;
- Any React / Vue / Vite / Node dependency;
- Any local HTTP server;
- Any CDN / external JS / CSS / font / Google Fonts usage;
- Any `localStorage` / `sessionStorage` usage;
- Any change to the Timeline / Overview existing entry points or behavior.

## Phase 4A.1 Implemented Scope

Phase 4A.1 is the Statistics / Export read-only hardening phase. It is a
hardening-only phase: no new features, no new backend write capability, no
new DB schema, no new bridge/API/service write method, no export write
action, no file creation, no save dialog, no folder opening, no Project
Rules migration, no Settings / Privacy migration, and no legacy UI removal.

Hardening implemented in Phase 4A.1:

- **Service layer** (`worktrace/services/statistics_service.py`):
  - Documented status inclusion semantics: all closed, non-hidden,
    non-deleted activities are aggregated regardless of status
    (`normal` / `idle` / `paused` / `excluded` / `error` are all included).
    The `by_status` breakdown surfaces each status group with a display
    label.
  - Documented `bool` / `None` / non-string input rejection: the
    `isinstance(date_from, str)` guard in `_validate_summary_date_range`
    rejects `bool` (which is not a `str`), `None`, `int`, and any other
    non-string type as `invalid_date`.
  - The stable tie-breaker for equal-duration groups (sort by
    `(-duration_seconds, display_name.casefold())`) is locked by tests so
    group order is deterministic across runs.
- **API layer** (`worktrace/api/statistics_api.py`):
  - Removed the duplicated date validation that was previously performed
    at both the API and service layers. The service layer now performs
    the canonical validation; the API wrapper maps `ValueError` (with its
    stable code token) to `StatisticsSummaryError` and collapses any
    unexpected exception to `operation_failed`.
  - A `ValueError` without a known code token (`invalid_date` /
    `invalid_range` / `range_too_large`) collapses to `operation_failed`
    so internal details never reach the bridge.
  - Removed the unused `date` import.
- **Bridge layer** (`worktrace/webview_ui/bridge.py`):
  - Added an explicit comment documenting that `isinstance(..., str)`
    rejects `None`, `bool`, `int`, and any other non-string type so
    `True` / `False` never reach the API/service validation.
  - The bridge method remains read-only: it never writes to the DB,
    never writes a file, and never opens a save dialog.
- **Frontend** (`worktrace/webview_ui/app.js`):
  - Added a loading double-click guard: `loadStatisticsExportSummary`
    checks `statisticsLoading` before doing any work, so concurrent
    triggers (quick range buttons, lazy load, manual click) cannot fire
    overlapping requests.
  - Added a client-side date range validator
    (`validateStatisticsDateRange`) that catches `invalid_date` /
    `invalid_range` / `range_too_large` before calling the bridge, giving
    the user an immediate clear Chinese message without a round-trip.
    The bridge and service still perform the canonical validation.
- **Tests**:
  - Added 18 Phase 4A.1 tests covering loading guard, client-side
    validator, no export write handler in the statistics section,
    `bool` / `None` / empty-string rejection at service and bridge
    layers, stable tie-breaker, all-known-statuses-included semantics,
    API delegation to service, unknown-ValueError collapse to
    `operation_failed`, docs mentions, schema unchanged, legacy UI not
    deleted, and no new WebView pages.

## Phase 4A.1 Not Implemented

Phase 4A.1 does not implement and does not start:

- Any export write action;
- Any CSV / Excel / PDF / timesheet file creation;
- Any save file dialog;
- Any folder opening;
- Any export write bridge / API / service method;
- Any DB schema change;
- Any DB write;
- Any live-time projection;
- Any Project Rules migration to WebView;
- Any Settings / Privacy migration to WebView;
- Any removal of the legacy Tkinter / CustomTkinter UI code;
- Any Tkinter fallback path;
- Any React / Vue / Vite / Node dependency;
- Any local HTTP server;
- Any CDN / external JS / CSS / font / Google Fonts usage;
- Any `localStorage` / `sessionStorage` usage;
- Any change to the Timeline / Overview existing entry points or behavior.

## Phase 4B Implemented Scope

Phase 4B is the **Export actions foundation — CSV export only** phase. It
introduces the first controlled file-write capability on the Statistics /
Export page: the user can pick a save location through a native save dialog
and export the current closed, non-hidden, non-deleted activities in the
chosen date range as a display-safe CSV file. Phase 4B does **not** add
Excel / PDF / timesheet export, does **not** open a folder, does **not**
auto-open the exported file, does **not** auto-submit a timesheet, does
**not** migrate Project Rules / Settings, does **not** change the DB
schema, and does **not** remove the legacy Tkinter UI.

Implemented in Phase 4B:

- **Shared helper** (`worktrace/formatters.py`):
  - Added `format_safe_display_name(row)` that returns the first non-empty
    value from the chain `resource_display_name` → `activity_display_name`
    → `app_name` → `process_name` → `"未知"`. This deliberately skips
    `window_title` / `file_path_hint` / `note` so the CSV resource-name
    column never surfaces a raw window title, file path, or note. The
    bridge Timeline detail row now delegates to this helper too, removing
    the previously duplicated fallback chain.
- **Service layer** (`worktrace/services/statistics_service.py`):
  - Promoted `_validate_summary_date_range` to the public
    `validate_statistics_date_range` so the export path reuses the exact
    same date rules as the read-only summary (`YYYY-MM-DD` only,
    `date_from <= date_to`, inclusive span ≤ 31 days; `None` / `bool` /
    non-string rejected). The private alias `_validate_summary_date_range`
    is retained for backwards compatibility.
  - Added `get_status_display_label(status_code)` returning the Chinese
    label for `normal` / `idle` / `paused` / `excluded` / `error` so the
    CSV status column is human-readable.
  - Updated `export_preview` in `get_statistics_export_summary`:
    `available_formats` is now `["csv"]` (timesheet is no longer
    advertised) and `export_actions_enabled` is now `True` (the CSV write
    is open).
- **Export service** (`worktrace/services/export_service.py`):
  - Added `build_statistics_csv_rows(date_from, date_to)` that reuses
    `validate_statistics_date_range` and
    `timeline_service.get_report_activity_rows(include_hidden=False)`,
    drops `is_in_progress` rows, and projects each row into a display-safe
    dict with the 10 ordered CSV columns. The resource name uses
    `format_safe_display_name`; raw `window_title` / `file_path_hint` /
    `full_path` / clipboard / `note` / traceback / SQL are never present.
  - Added `write_statistics_csv(date_from, date_to, output_path)` that
    validates dates, normalizes the `.csv` suffix (auto-appends /
    replaces non-csv suffix), rejects a directory path or a
    missing-parent path as `invalid_path`, raises `ValueError("empty_data")`
    for an empty range (no file is created), and writes the CSV with
    `newline=""` and `encoding="utf-8-sig"` (UTF-8 BOM) so Excel opens
    Chinese headers correctly. Each text cell is passed through
    `_escape_csv_cell` to mitigate CSV formula injection (cells starting
    with `=` / `+` / `-` / `@` / tab get a single leading quote).
    Returns `{"activity_count", "duration_seconds", "filename"}` where
    `filename` is the basename only (never the full local path).
    `PermissionError` / `OSError` are allowed to propagate so the API
    layer can map them to stable codes. This function only writes the
    chosen CSV file — it never writes to the DB, never updates
    `activity_log.updated_at`, never opens a folder, never opens the
    exported file, and never auto-submits a timesheet.
- **API layer** (`worktrace/api/export_api.py`):
  - Added `StatisticsExportError(ValueError)` with a stable `code`
    attribute. Documented codes: `invalid_date` / `invalid_range` /
    `range_too_large` / `empty_data` / `invalid_path` /
    `permission_denied` / `file_busy` / `write_failed` /
    `operation_failed`.
  - Added `export_statistics_csv(date_from, date_to, output_path)` that
    delegates to `export_service.write_statistics_csv` and maps
    `ValueError` (with a known code token) to the matching stable code,
    `PermissionError` → `permission_denied`, `OSError` → `file_busy`,
    and any unknown exception → `operation_failed`. Error messages never
    contain the raw exception text, full path, SQL, traceback, or
    sensitive fields.
- **Bridge layer** (`worktrace/webview_ui/bridge.py`):
  - Added `_STATISTICS_EXPORT_ERROR_MESSAGES` mapping each stable code
    to a stable Chinese message. `permission_denied` / `file_busy` /
    `write_failed` share one message so a low-level OS failure never
    distinguishes which kind of write error occurred.
  - Added `WebViewBridge.__init__` storing `self._window: Any = None` and
    `set_window(window)` so `webview_main.py` can inject the pywebview
    window after `create_window` returns. Importing the bridge module
    does NOT start the GUI; `set_window` only stores the reference.
  - Added `export_statistics_csv(date_from, date_to)` that validates the
    obvious date shape, opens the native save dialog via the injected
    window, returns `{"ok": False, "cancelled": True, "error":
    "已取消导出"}` on user cancel (no API write is called), returns
    `{"ok": True, "filename", "activity_count", "duration",
    "cancelled": False}` on success (basename only — full path never
    leaves the bridge), and returns `{"ok": False, "error": "<chinese>",
    "cancelled": False}` on any failure. Unknown exceptions collapse to
    `"导出失败"`.
  - Added `_choose_csv_save_path()` that lazily imports `pywebview`
    inside the method (so the bridge module does not pull the WebView
    backend into unit tests), resolves the save-dialog type constant
    (`FileDialog.SAVE` first, deprecated `SAVE_DIALOG` as fallback),
    and calls `window.create_file_dialog(...)`. Raises
    `StatisticsExportError("operation_failed")` if no window is injected
    or the pywebview API is unavailable.
- **WebView entry** (`worktrace/webview_main.py`):
  - Captured the `webview.create_window(...)` return value and called
    `bridge.set_window(window)` before `webview.start()` so the bridge
    can open the native save dialog from a JS callback. This does not
    start the GUI on import and does not require admin privileges.
- **Frontend** (`worktrace/webview_ui/index.html`, `app.js`, `styles.css`):
  - The statistics page subtitle now announces CSV export is open:
    `查看统计并导出当前范围内的活动记录为 CSV 文件。`
  - The export hint now reads: `当前支持 CSV 导出。导出范围最多 31 天，
    仅包含已结束的非隐藏记录，不含窗口标题、文件路径等敏感信息。
    暂不支持 Excel、PDF、timesheet 模板、打开文件夹或自动提交工时。`
  - The disabled placeholder button is replaced with a real action button
    `导出 CSV` plus a dedicated `stats-export-status` element.
  - Added `statisticsExportSaving` as a separate guard so the CSV write
    cannot be double-triggered or overlap a statistics load. Both the
    export button and the load button are disabled while either is in
    flight.
  - Added `setStatisticsExportStatus(message, kind)` with `info` /
    `success` / `error` CSS variants and `setStatisticsExportSaving(saving)`
    that toggles both buttons.
  - Added `exportStatisticsCsv()` that reuses
    `validateStatisticsDateRange` for the client-side pre-check, calls
    `callBridge("export_statistics_csv", ...)`, handles `cancelled` as a
    clean info status, surfaces `导出成功：<filename>（<count> 条，共
    <duration>）` on success, and collapses any unexpected `.catch` to
    `导出失败` (never reads `err.message`).
  - CSS: `.stats-export-action-btn` is now an enabled blue pointer
    button; `:disabled` shared style retained for both load and export
    buttons.
- **Tests**:
  - Added `tests/test_statistics_csv_export.py` with 54 tests covering
    service build/write (UTF-8 BOM, Chinese headers, multi-day range,
    hidden / deleted / in-progress exclusion, all-statuses inclusion,
    empty-data no-file, invalid date / range / range-too-large, bool /
    None rejection, no raw sensitive fields, CSV formula injection
    escaping, permission / file-busy / OSError mapping, no DB writes,
    no resource / assignment / session-note mutation, path extension
    normalization, directory / missing-parent rejection), API layer
    (success payload, all stable error codes, error message never leaks
    internals), and bridge layer (basename-only return, cancel does not
    call API, all stable Chinese messages, no full path in payload,
    no backend-internals import, read-only summary still preserved,
    `set_window` does not start GUI).
  - Updated the 8 Phase 4A / 4A.1 regression tests that locked the old
    read-only subtitle / disabled button / `not-allowed` CSS / `["csv",
    "timesheet"]` formats / `export_actions_enabled is False` to reflect
    the Phase 4B enabled CSV write semantics.
  - Added 13 Phase 4B frontend static tests in
    `tests/test_webview_resources.py` covering bridge call wiring,
    `statisticsExportSaving` guard, `validateStatisticsDateRange`
    pre-check, catch-block never reads raw exception text, cancel /
    success payload shape, no `export_excel` / `export_pdf` /
    `export_timesheet` / `open_folder` / auto-submit references,
    `set_window` does not start GUI, `webview_main.py` injects window
    before `webview.start()`, dedicated export status element and CSS,
    no `localStorage` / `sessionStorage`, no external links / CDN /
    Google Fonts.

## Phase 4B Not Implemented

Phase 4B does not implement and does not start:

- Any Excel export;
- Any PDF export;
- Any timesheet advanced template;
- Any folder opening;
- Any auto-open of the exported CSV file;
- Any auto-submit of a timesheet;
- Any DB schema change;
- Any migration of Project Rules to WebView;
- Any migration of Settings / Privacy to WebView;
- Any removal of the legacy Tkinter / CustomTkinter UI code;
- Any Tkinter fallback path;
- Any React / Vue / Vite / Node dependency;
- Any local HTTP server;
- Any CDN / external JS / CSS / font / Google Fonts usage;
- Any `localStorage` / `sessionStorage` usage;
- Any change to the Timeline / Overview existing entry points or behavior.

## Phase 4B.1 Implemented Scope

Phase 4B.1 is the **CSV export hardening / native dialog + packaging
validation** phase. It is a hardening-only phase on top of Phase 4B: it
adds **no** new export format, no new product feature, and no new
user-visible behavior. The CSV export write path is locked down to
release quality, and the Phase 4B packaging gap (full PyInstaller /
installer validation) is closed.

Implemented / hardened in Phase 4B.1:

- **Native save dialog compatibility hardening** —
  `WebViewBridge._choose_csv_save_path` / `export_statistics_csv` were
  verified and locked with precision tests:
  - `FileDialog.SAVE` is tried first; the deprecated `SAVE_DIALOG`
    constant is kept as a fallback for older pywebview releases.
  - All `create_file_dialog` return shapes are handled stably:
    `None`, empty `list`/`tuple`, a single string, a `list`/`tuple`
    containing one or more paths.
  - Missing window injection, missing `FileDialog` / `SAVE_DIALOG`
    constants, and any dialog exception collapse to a stable
    `StatisticsExportError("operation_failed")` -> Chinese
    `导出失败`. No raw exception / traceback reaches the frontend.
  - User cancel returns `{"ok": False, "cancelled": True,
    "error": "已取消导出"}` and does NOT invoke the API write.
  - Success payload returns only `filename` (basename); no full path,
    parent directory name, or temp directory name is leaked.
- **Service / API path hardening** — `write_statistics_csv` and
  `export_statistics_csv` were verified to:
  - Preserve an explicit `.csv` suffix regardless of case (`.csv`,
    `.CSV`, `.Csv`) instead of re-appending `.csv`.
  - Replace non-`.csv` suffixes (`.txt`, no extension) with `.csv`.
  - Reject directory targets and missing parent directories as
    `invalid_path`.
  - Raise `empty_data` for empty ranges without creating a file.
  - Propagate `PermissionError` / `OSError` for API-level mapping to
    stable Chinese codes; unknown exceptions collapse to
    `operation_failed`.
  - Keep the existing UTF-8 BOM, Chinese header, formula-injection
    escaping (`=`, `+`, `-`, `@`, tab), display-safe field chain, and
    31-day / closed-only / hidden-excluded / deleted-excluded /
    in-progress-excluded / no-DB-write invariants.
- **Frontend split-file static contract hardening** — `js/statistics.js`
  was verified (and locked with new static tests) to keep:
  - A separate `statisticsExportSaving` guard distinct from
    `statisticsLoading`; export refuses to run while loading and vice
    versa.
  - `setStatisticsExportSaving` disables both the export button and
    the load button; `setStatisticsLoading` disables the export button.
  - `validateStatisticsDateRange` reuse before export.
  - Catch branch that never reads `err.message` / `reason.message` /
    raw exception.
  - Success display limited to filename / count / duration; cancel
    display `已取消导出`.
  - No `localStorage` / `sessionStorage`, no external links, no
    `export_excel` / `export_pdf` / `export_timesheet` /
    `open_folder` / `auto_submit` handlers.
- **WebView entry / packaging path hardening** — `webview_main.main`
  was verified to call `bridge.set_window(window)` BEFORE
  `webview.start()`; importing `worktrace.webview_main` does not
  start the GUI; `resource_path()` resolves for both source and
  `_MEIPASS`; `WorkTrace.spec` collects all six R2 split
  `js/*.js` modules (`core.js`, `overview.js`, `timeline.js`,
  `timeline_correction.js`, `statistics.js`, `init.js`) and does NOT
  collect `app.js`; `index.html` loads the six modules in the
  documented order and does NOT reference `app.js`.
- **Documentation boundary cleanup** — README, current-state,
  ui-webview-migration, release-validation, and this file were
  updated to mark Phase 4B.1 as the current hardening phase and to
  restate the export / packaging / forbidden-feature boundaries.
- **PyInstaller / installer validation** — the full
  `pyinstaller WorkTrace.spec --clean --noconfirm` build was run and
  the bundle was verified to collect the split `js/*.js` resources.

Phase 4B.1 also re-ran the full pytest suite (csv export, statistics
api, webview bridge, webview static contract, webview packaging, and
all earlier-phase regression tests).

## Phase 4B.1 Not Implemented

Phase 4B.1 does not implement and does not start:

- Any Excel export;
- Any PDF export;
- Any timesheet advanced template;
- Any folder opening;
- Any auto-open of the exported CSV file;
- Any auto-submit of a timesheet;
- Any DB schema change;
- Any migration of Project Rules to WebView;
- Any migration of Settings / Privacy to WebView;
- Any removal of the legacy Tkinter / CustomTkinter UI code;
- Any Tkinter fallback path;
- Any React / Vue / Vite / Node dependency;
- Any local HTTP server;
- Any CDN / external JS / CSS / font / Google Fonts usage;
- Any `localStorage` / `sessionStorage` usage;
- Any change to the Timeline / Overview existing entry points or
  behavior;
- Any rewrite of the existing, already-stable Phase 4B runtime code
  (per the Phase 4B.1 instruction: "如当前实现已满足，补充更精确测试
  即可；不要重写稳定代码").

## Phase 5A Implemented Scope

Phase 5A is the **Project Rules WebView read-only foundation** phase. It
migrates the Project Rules page from a WebView placeholder to a usable
read-only WebView page backed by the existing
`project_api.list_project_bindings()` read path. It does not add any
Project Rules write workflow and does not change existing data semantics.

Implemented in Phase 5A:

- **Bridge layer** (`worktrace/webview_ui/bridge.py`):
  - Added `get_project_rules`, a read-only bridge method that delegates to
    `project_api.list_project_bindings()` and builds a display-oriented
    payload for WebView.
  - Each project payload includes id, name, description, enabled state,
    created_by, special `排除规则` detection, summary text, folder /
    keyword / total counts, and a flattened display rule list.
  - Folder rules are projected as `kind="folder"` / `kind_label="文件夹"`
    with `folder_path` as target, enabled state, recursive scope, and
    detail text containing project ownership, recursion scope, and state.
  - Keyword rules are projected as `kind="keyword"` /
    `kind_label="关键词"` with `keyword` as target, enabled state,
    `recursive=None`, and detail text containing project ownership and
    state.
  - Failures return exactly `{"ok": False, "error": "加载项目规则失败",
    "projects": []}`. Tracebacks, SQL, raw exception text, window titles,
    clipboard, notes, and backend row internals are not surfaced.
- **Frontend** (`worktrace/webview_ui/index.html`,
  `worktrace/webview_ui/js/core.js`, `worktrace/webview_ui/js/rules.js`,
  `worktrace/webview_ui/js/init.js`, `worktrace/webview_ui/styles.css`):
  - Replaced the `page-rules` placeholder with a real read-only page titled
    `项目规则`, a subtitle explaining the folder / keyword rule view, stable
    loading / error / list / empty / readonly-hint DOM anchors, and no
    action buttons.
  - Added `rules.js` as a local classic script under the shared
    `window.WorkTraceApp` namespace, loaded after `statistics.js` and
    before `init.js`; no ES modules, Node, bundler, browser storage, remote
    resources, or frontend file writes were introduced.
  - Added `rulesLoaded`, `rulesLoading`, and `rulesRequestToken` state to
    `core.js`; `init.js` lazy-loads Project Rules on first navigation and
    refreshes it only when the page is active and already loaded.
  - Added read-only rendering for project cards, rule count summaries,
    folder / keyword badges, targets, enabled / disabled states, recursive
    folder scope, special `排除规则` marker, empty state, loading state, and
    stable Chinese failure state.
  - All dynamic text is escaped through the shared frontend helpers before
    insertion into `innerHTML`; catch paths collapse to `加载项目规则失败` and
    do not read raw exception `.message` fields.
- **Packaging / static coverage**:
  - Added `rules.js` to `tests/webview/static_helpers.py` and
    `WorkTrace.spec` so static tests and PyInstaller packaging include the
    new split module in the correct load order.
- **Tests**:
  - Added `tests/webview/test_project_rules_static_contract.py` covering the
    migrated page structure, script load order, shared state variables,
    read-only bridge call, absence of Project Rules write method calls,
    stable catch-path behavior, frontend no-storage / no-remote-resource
    boundary, and no export / folder-open / auto-submit controls on the
    Project Rules page.
  - Added `tests/test_webview_project_rules_bridge.py` covering successful
    payload shape, field types, folder / keyword mapping, disabled
    project/rule states, special `排除规则` summary, empty list behavior,
    exception collapse, sensitive text exclusion, and bridge import
    boundary.
  - Added a lightweight service regression proving
    `project_service.list_project_bindings()` returns user projects plus
    the special excluded project, groups folder / keyword rules under the
    owning project, preserves the existing ordering, and does not change DB
    row counts when called as a read-only path.
- **Documentation**:
  - Updated README, current-state, and the migration summary to mark Phase
    5A as current, list Project Rules as a migrated read-only WebView page,
    remove Project Rules from the unmigrated-page list, preserve Phase 4B /
    4B.1 CSV export boundaries, and restate unsupported Project Rules write
    workflows and Phase 6 Settings / Privacy / Encrypted Backup migration.

## Phase 5A Not Implemented

Phase 5A does not implement and does not start:

- Project creation, editing, deletion, archive, or enable/disable in
  WebView;
- Folder rule creation, editing, deletion, or enable/disable in WebView;
- Keyword rule creation, editing, deletion, or enable/disable in WebView;
- Folder rule conflict preview;
- Folder rule backfill;
- Automatic rules;
- Batch Project Rules operations;
- Settings / Privacy / Encrypted Backup WebView migration;
- Excel export;
- PDF export;
- Timesheet export or auto-submit;
- Folder opening or auto-open of exported files;
- DB schema changes;
- Legacy Tkinter UI removal;
- Tkinter fallback path;
- React / Vue / Vite / Node dependency;
- Local HTTP / FastAPI server;
- CDN / external JS / CSS / font / Google Fonts usage;
- `localStorage` / `sessionStorage` usage;
- Network requests;
- Any change to the existing Timeline, Statistics / CSV export, collector,
  privacy, encrypted backup, or database semantics.

## Phase 5A.1 Implemented Scope

Phase 5A.1 is the **Project Rules WebView read-only hardening** phase. It is
hardening-only / regression-only on top of Phase 5A: Phase 5A remains the last
Project Rules behavior-change phase, and Phase 5A.1 does not add any Project
Rules write workflow or product feature.

Implemented / hardened in Phase 5A.1:

- **Bridge payload contract hardening** —
  `WebViewBridge.get_project_rules` still delegates only to
  `project_api.list_project_bindings()` and still returns
  `{"ok": True, "projects": [...]}` on success or exactly
  `{"ok": False, "error": "加载项目规则失败", "projects": []}` on failure.
  The read-only payload projection now tolerates malformed project / rule
  rows, missing `folder_rules` / `keyword_rules`, missing descriptions,
  missing folder paths / keywords, non-int ids, and dirty boolean values
  without exposing tracebacks, SQL, raw exception text, window titles,
  clipboard, notes, or backend row internals to JS.
- **Frontend read-only display contract hardening** —
  `js/rules.js` keeps the existing read-only DOM and UI text, keeps dynamic
  rendering behind the shared escape helpers, uses request tokens to avoid
  stale response overwrites, keeps existing rendered data visible on failure,
  collapses all load failures to `加载项目规则失败`, and does not bind any
  Project Rules write button or write bridge call.
- **Init / refresh regression lock** —
  `init.js` still lazy-loads Project Rules only when the user first enters
  the rules page, avoids concurrent Project Rules loads, and refreshes
  Project Rules only when the active page is `rules` and the page has already
  loaded once. Overview / Timeline / Statistics refresh behavior is not
  changed.
- **Static / packaging contract lock** —
  static tests now pin `rules.js` between `statistics.js` and `init.js` in
  both `index.html` and `tests/webview/static_helpers.py`, verify
  `rulesLoaded` / `rulesLoading` / `rulesRequestToken`, loading and stale
  guards, read-only bridge call wiring, absence of Project Rules write calls
  and unsupported export / open-folder / auto-submit controls, no browser
  storage or remote resources, and `WorkTrace.spec` inclusion of
  `worktrace/webview_ui/js/rules.js`.
- **Service regression coverage** —
  the existing read-only `project_service.list_project_bindings()` regression
  remains the service contract: user projects plus the special excluded
  project are grouped stably, folder / keyword rule ownership is preserved,
  ordering is stable, and a read-only call does not change DB row counts.
- **Documentation boundary sync** —
  README, current-state, migration summary, and this history now mark Phase
  5A.1 as the current hardening phase, state that Project Rules is migrated
  as a read-only WebView page, and preserve the unsupported boundaries for
  Project Rules writes, Phase 6 Settings / Privacy / Encrypted Backup,
  Phase 4B / 4B.1 CSV-only export, legacy Tkinter reference-only code, DB
  schema, frontend dependencies, network, and unsupported export/automation
  workflows.

## Phase 5A.1 Not Implemented

Phase 5A.1 does not implement and does not start:

- Project creation, editing, deletion, archive, or enable/disable in
  WebView;
- Folder rule creation, editing, deletion, or enable/disable in WebView;
- Keyword rule creation, editing, deletion, or enable/disable in WebView;
- Folder rule conflict preview;
- Folder rule backfill;
- Automatic rules;
- Batch Project Rules operations;
- Settings / Privacy / Encrypted Backup WebView migration;
- Excel export;
- PDF export;
- Timesheet export or auto-submit;
- Folder opening or auto-open of exported files;
- DB schema changes;
- Legacy Tkinter UI removal;
- Tkinter fallback path;
- React / Vue / Vite / Node dependency;
- Local HTTP / FastAPI server;
- CDN / external JS / CSS / font / Google Fonts usage;
- `localStorage` / `sessionStorage` usage;
- Network requests;
- Any change to the existing Timeline, Statistics / CSV export, Overview,
  collector, privacy, encrypted backup, or database semantics.

## Phase 5B Implemented Scope

Phase 5B is the **Project Rules rule enable/disable foundation** phase. It is
the first minimal Project Rules WebView write phase and only allows enabling
or disabling one existing folder rule or keyword rule at a time. The write is
reversible, refreshes the current Project Rules list after success, and does
not change historical activity classification or schema.

Implemented in Phase 5B:

- **API layer** (`worktrace/api/rule_api.py`):
  - Added a narrow `set_project_rule_enabled(rule_type, rule_id, enabled)`
    facade for WebView writes.
  - `rule_type` is limited to `folder` / `keyword`; `rule_id` must be a
    positive `int` and explicitly rejects bool, `None`, strings, floats, zero,
    and negative ids; `enabled` must be a real bool and rejects `0` / `1` /
    strings / `None`.
  - Existing rule existence is checked before update, so SQLite UPDATE no-op
    behavior is not used as success.
  - Errors return stable codes (`invalid_input`, `not_found`,
    `operation_failed`) for the bridge to map to Chinese text. Raw service
    `ValueError` text does not cross the API boundary.
  - The facade delegates to the existing keyword / folder service write paths,
    preserving keyword rule cache, folder rule cache, and privacy exclude cache
    invalidation semantics. It does not call backfill and does not touch
    `activity_log`, `activity_project_assignment`, or `project_session_note`.
- **Bridge layer** (`worktrace/webview_ui/bridge.py`):
  - Added `set_project_rule_enabled(rule_type, rule_id, enabled)`.
  - Bridge validation rejects invalid `rule_type`, bool-as-int ids, non-positive
    ids, and non-bool enabled values before calling `rule_api`.
  - Success returns `{"ok": True, "rule_type": "...", "rule_id": n,
    "enabled": true/false}`.
  - Failure returns stable Chinese messages only: `操作无效`, `规则不存在`, or
    `更新规则状态失败`. Tracebacks, SQL, raw exception text, paths, window
    titles, clipboard, notes, and internal fields are not returned.
  - The bridge still imports only `worktrace.api` from the backend. It does
    not import services, db, collector, security, runtime, or config.
- **Frontend** (`worktrace/webview_ui/index.html`,
  `worktrace/webview_ui/js/core.js`, `worktrace/webview_ui/js/rules.js`,
  `worktrace/webview_ui/styles.css`):
  - Rules rows now show `已启用` / `已停用` state and an `启用` / `停用`
    button for existing folder / keyword rules only.
  - Clicking a rule toggle calls only
    `App.callBridge("set_project_rule_enabled", ruleType, ruleId, nextEnabled)`.
  - Added `rulesSavingRuleKey` so one rule update is in flight at a time; the
    active button shows `正在更新…`.
  - Disabling asks for confirmation: `确定停用这条规则吗？停用后它将不再用于自动归类。`
  - Success refreshes Project Rules and shows `规则状态已更新`; failure keeps the
    existing rendered list visible and shows stable Chinese fallback text.
  - Catch paths do not read `err.message` / `error.message`; dynamic fields
    continue to render through escaping helpers.
  - No `app.js` was reintroduced. No React / Vue / Vite / Node, local HTTP
    server, CDN, external JS/CSS/fonts, network requests, or browser storage
    were introduced.
- **Tests**:
  - Added `tests/test_project_rules_enable_disable.py` for API/service behavior,
    stable error codes, invalid input, existing-rule toggles, cache
    invalidation paths, no backfill, no new/deleted project/rule rows, and no
    changes to activity, assignment, or session-note row counts.
  - Updated `tests/test_webview_project_rules_bridge.py` for bridge success,
    invalid input, bool id rejection, invalid enabled rejection, not-found
    mapping, unknown exception collapse, JSON-serializable payloads, no
    sensitive leakage, import boundary, and unchanged `get_project_rules`.
  - Updated `tests/webview/test_project_rules_static_contract.py` for the
    allowed `set_project_rule_enabled` call, saving guard, confirmation,
    success refresh, stable failure behavior, no raw exception reads, no
    forbidden Project Rules handlers, no project enable/disable handler, no
    storage/network, script order, and no `app.js`.
- **Documentation**:
  - README, current-state, migration summary, and this history now mark Phase
    5B as current, describe the existing-rule enable/disable-only scope, and
    restate all not-yet-open boundaries.

## Phase 5B Not Implemented

Phase 5B does not implement and does not start:

- Project creation, editing, deletion, archive, or enable/disable in WebView;
- Folder rule creation, editing, or deletion in WebView;
- Keyword rule creation, editing, or deletion in WebView;
- Folder rule conflict preview;
- Folder rule backfill;
- Automatic rules;
- Batch Project Rules operations;
- Settings / Privacy / Encrypted Backup WebView migration;
- Excel export;
- PDF export;
- Timesheet export or auto-submit;
- Folder opening or auto-open of exported files;
- DB schema changes;
- Legacy Tkinter UI removal;
- Tkinter fallback path;
- React / Vue / Vite / Node dependency;
- Local HTTP / FastAPI server;
- CDN / external JS / CSS / font / Google Fonts usage;
- `localStorage` / `sessionStorage` usage;
- Network requests;
- Any change to the existing Timeline, Statistics / CSV export, Overview,
  collector, privacy, encrypted backup, or database semantics.

## Phase 5B.1 Implemented Scope

Phase 5B.1 is the **Project Rules rule enable/disable hardening** phase. It
is a hardening-only / regression-only follow-up to Phase 5B (the most recent
behavior-change phase). It does not introduce any new Project Rules
capability: the only Project Rules WebView write path remains
`rule_api.set_project_rule_enabled` / `WebViewBridge.set_project_rule_enabled`,
which enables or disables one existing folder rule or keyword rule at a
time. Phase 5B.1 locks the existing correct behavior across the API,
bridge, and frontend, and fixes one real bug discovered while writing the
regression tests.

Implemented in Phase 5B.1:

- **Bug fix (real runtime bug)**:
  - `rule_api.set_project_rule_enabled` previously used
    `if rule_type not in {"folder", "keyword"}:`, which raises
    `TypeError: unhashable type: 'list'` for unhashable non-string
    `rule_type` values (e.g. `[]`, `{}`). The spec requires non-string types
    to collapse to the stable `invalid_input` code, so the check now reads
    `if not isinstance(rule_type, str) or rule_type not in {"folder", "keyword"}:`,
    which short-circuits before the set membership lookup for any non-string
    input.
  - `WebViewBridge.set_project_rule_enabled` had the same set-membership
    check. For unhashable non-string `rule_type` values the bridge caught
    the resulting `TypeError` in its outer `except` and returned the wrong
    stable message `更新规则状态失败` instead of the spec-required
    `操作无效`. The same `isinstance(rule_type, str)` short-circuit was
    added so non-string `rule_type` values now collapse to `操作无效` at
    the bridge layer without crossing `rule_api`.
  - No other runtime behavior changed. The bug only manifested when JS
    passed an unhashable non-string value to the bridge (the frontend never
    does this), but the spec explicitly requires the API and bridge to
    reject all non-string `rule_type` inputs with the stable code, so the
    fix is in scope.
- **API layer hardening** (`worktrace/api/rule_api.py`):
  - `rule_type` validation now rejects every non-string type (including
    unhashable `list` / `dict`) without leaking a `TypeError`.
  - Existing `_valid_rule_id` / `_valid_enabled` helpers and the
    pre-update existence check (`_rule_exists`) are unchanged. SQLite
    UPDATE no-op behavior on a missing rule still returns `not_found`, never
    success.
  - Unknown exceptions from `rule_service.set_rule_enabled` /
    `folder_rule_service.set_folder_rule_enabled` still collapse to
    `operation_failed` and never surface raw exception text, SQL,
    tracebacks, paths, window titles, clipboard, or notes.
- **Bridge layer hardening** (`worktrace/webview_ui/bridge.py`):
  - `set_project_rule_enabled` now applies the same `isinstance(rule_type,
    str)` short-circuit so unhashable non-string inputs return `操作无效`
    instead of falling through to the generic `更新规则状态失败`.
  - Success payload remains the narrow
    `{"ok": True, "rule_type": "folder"|"keyword", "rule_id": int,
    "enabled": bool}` shape; the bridge does not return a refreshed
    Project Rules list on the toggle write path (JS calls
    `get_project_rules` after success).
  - Failure payloads remain the stable Chinese messages only
    (`操作无效` / `规则不存在` / `更新规则状态失败`); tracebacks, SQL,
    raw exception text, paths, window titles, clipboard, and notes are
    never surfaced.
- **Frontend hardening** (`worktrace/webview_ui/js/rules.js`,
  `worktrace/webview_ui/js/init.js`):
  - No source change. The existing single-in-flight guard
    (`App.rulesSavingRuleKey`), confirmation dialog for disable, dataset
    parse / validation, success-then-refresh chain, failure-keeps-rendered-
    list behavior, stale-response guard (`App.rulesRequestToken`), escape
    helpers, and catch paths that never read `.message` are locked by the
    new static contract tests below.
  - `init.js` still lazy-loads Project Rules on first navigation only and
    refreshes only when the page is active and not currently loading or
    saving. No Project Rules create/edit/delete/project-toggle event is
    bound.
- **Tests**:
  - `tests/test_project_rules_enable_disable.py`: added parametrized
    regression locks for invalid `rule_type` variants (None, empty,
    `project`, `folder_rule`, `keyword_rule`, `Folder`, `KEYWORD`,
    `PROJECT`, plurals, unknown strings, ints, floats, bool, `list`,
    `dict`), extra invalid `rule_id` variants (`abc`, `1.5`, `2.5`,
    `0.5`, `-999`, `[]`, `{}`, `true`), extra invalid `enabled` variants
    (`1`, `0`, `True`, `False`, `1.0`, `0.0`, `[]`, `{}`), service
    exception folding for both keyword and folder paths, existence-check-
    before-update, no-conflict-preview, idempotent same-value toggle,
    privacy/exclude cache invalidation for both keyword and folder paths,
    explicit row-count lock across multiple toggle cycles, and JSON-
    serializable stable success payload.
  - `tests/test_webview_project_rules_bridge.py`: added parametrized
    regression locks for invalid `rule_type` / `rule_id` / `enabled`
    variants, sensitive-text exclusion on every failure path (invalid
    input / not_found / unknown exception), success payload never returns
    a full refreshed project list, toggle path never calls any other
    Project Rules write API (project enable/disable / project / rule
    create / edit / delete / conflict preview / backfill), stable
    `rule_type` / `rule_id` / `enabled` field types on success, and
    unchanged `get_project_rules` payload.
  - `tests/webview/test_project_rules_static_contract.py`: added regression
    locks for the toggle button being inside the rule row (not the project
    card), the saving state clearing on success/failure/rejected-promise
    paths, the single-in-flight guard ordering, the `正在更新…` saving
    label, success-then-refresh ordering, failure-keeps-rendered-list
    behavior, dataset id parse / validation, dataset rule-type validation,
    cancellation-does-not-call-bridge, no duplicate static DOM ids in the
    page-rules section, loading / saving / error / empty state isolation,
    the only-allowed `set_project_rule_enabled` bridge call, and no
    create/edit/delete/project-toggle event binding in `init.js`.
- **Documentation**:
  - README, current-state, migration summary, and this history now mark
    Phase 5B.1 as current, describe the hardening-only / regression-only
    scope, name the unhashable-`rule_type` fix, and restate all not-yet-open
    boundaries. Phase 4B / 4B.1 CSV export boundaries are preserved.
  - No DB schema change. No legacy Tkinter UI removal. No new dependency.
    No new frontend framework / network / browser storage.

## Phase 5B.1 Not Implemented

Phase 5B.1 does not implement and does not start:

- Project creation, editing, deletion, archive, or enable/disable in WebView;
- Folder rule creation, editing, or deletion in WebView;
- Keyword rule creation, editing, or deletion in WebView;
- Folder rule conflict preview;
- Folder rule backfill;
- Automatic rules;
- Batch Project Rules operations;
- Settings / Privacy / Encrypted Backup WebView migration;
- Excel export;
- PDF export;
- Timesheet export or auto-submit;
- Folder opening or auto-open of exported files;
- DB schema changes;
- Legacy Tkinter UI removal;
- Tkinter fallback path;
- React / Vue / Vite / Node dependency;
- Local HTTP / FastAPI server;
- CDN / external JS / CSS / font / Google Fonts usage;
- `localStorage` / `sessionStorage` usage;
- Network requests;
- Any change to the existing Timeline, Statistics / CSV export, Overview,
  collector, privacy, encrypted backup, or database semantics.

## Phase 5C Implemented Scope

Phase 5C is the **Project Rules keyword rule creation foundation** phase. It
opens one minimal new Project Rules write capability: creating a single
keyword rule on an existing rule-target project from the WebView Project
Rules page, then refreshing the list on success. It is the first new
Project Rules write path beyond the Phase 5B / 5B.1 existing folder /
keyword rule enable/disable toggle, and it deliberately does not open any
other Project Rules write workflow. The write does not change historical
activity classification or schema.

Implemented in Phase 5C:

- **API layer** (`worktrace/api/rule_api.py`):
  - Added a narrow `create_project_keyword_rule(project_id, keyword)` facade
    for WebView writes. It creates exactly one keyword rule on an existing
    rule-target project and nothing else.
  - `project_id` must be a real `int` and `> 0`; bool-as-int, `None`,
    numeric strings, floats, zero, negative ints, lists, and dicts are
    rejected with the stable `invalid_input` code.
  - `keyword` must be a real `str`; `None`, bool, int / float, list / dict
    are rejected. `keyword.strip()` must be non-empty; the trimmed value is
    used for creation.
  - Project eligibility reuses the existing
    `project_api.list_rule_target_projects()` semantics (active, non-archived
    user projects plus the special `排除规则` project when it is an eligible
    target). No new project-eligibility rule is invented.
  - Duplicate keyword rules (same `project_id` + trimmed `keyword`) return
    the stable `duplicate_rule` code; no second row is created.
  - Unknown project returns `project_not_found`. Raw service exceptions
    collapse to `operation_failed`. Tracebacks, SQL, raw exception text,
    paths, window titles, clipboard, and notes never cross the API boundary.
  - The facade delegates to the existing `rule_service.create_rule` write
    path, preserving keyword rule cache invalidation and privacy exclude
    cache clearing. It does not call backfill, conflict preview, or any
    folder-rule write path, and does not touch `activity_log`,
    `activity_project_assignment`, or `project_session_note`.
  - Success returns `{"ok": True, "rule": {"kind": "keyword", "id": int,
    "project_id": int, "keyword": str, "enabled": True}}`. The API does not
    return a refreshed Project Rules list (the frontend calls
    `get_project_rules` after success).
- **Bridge layer** (`worktrace/webview_ui/bridge.py`):
  - Added `create_project_keyword_rule(project_id, keyword)`.
  - Bridge validation mirrors the API: rejects bool-as-int `project_id`,
    non-positive ids, non-string `keyword`, and whitespace-only `keyword`
    before calling `rule_api`, returning `操作无效`.
  - Success returns the narrow `{"ok": True, "rule": {...}}` shape with
    coerced `int` / `str` / `bool` field types.
  - Failure returns stable Chinese messages only: `操作无效`
    (`invalid_input`), `项目不存在` (`project_not_found`), `关键词规则已存在`
    (`duplicate_rule`), `新增关键词规则失败` (`operation_failed` and any
    unknown code / exception). Tracebacks, SQL, raw exception text, paths,
    window titles, clipboard, notes, backend error codes, and internal
    fields are never surfaced.
  - The bridge still imports only `worktrace.api` from the backend. It does
    not import services, db, collector, security, runtime, or config, and
    does not call any other Project Rules write API.
- **Frontend** (`worktrace/webview_ui/index.html`,
  `worktrace/webview_ui/js/core.js`, `worktrace/webview_ui/js/rules.js`,
  `worktrace/webview_ui/js/init.js`, `worktrace/webview_ui/styles.css`):
  - Added a minimal keyword create form with stable DOM anchors:
    `rules-keyword-create-form`, `rules-keyword-create-project` (a `<select>`
    populated from the loaded Project Rules data), `rules-keyword-create-input`
    (a text `<input>`), `rules-keyword-create-submit` (the only new static
    button), `rules-keyword-create-empty` (empty hint when no target project
    is available), and `rules-keyword-create-status` (status line).
  - Added `App.rulesCreatingKeyword` state, separate from the Phase 5B
    `App.rulesSavingRuleKey` toggle state, so the two write paths never
    pollute each other. Only one keyword create may be in flight at a time.
  - The submit handler validates `project_id` (`parseInt` + `> 0`) and
    `keyword` (non-empty after `trim()`) before calling
    `App.callBridge("create_project_keyword_rule", projectId, keyword)`.
    During creation the button shows `正在新增…` and repeats are blocked.
  - Success clears the keyword input, then calls `App.loadProjectRules()` to
    refresh the list. Failure keeps the rendered list and the keyword input
    intact so the user can edit and retry.
  - The project selector is only re-populated when no keyword create is in
    flight, so an auto-refresh never displaces an in-flight submit. The
    existing `App.rulesRequestToken` stale guard is preserved.
  - Catch paths do not read `err.message` / `error.message`; dynamic text is
    rendered through escaping / safe-text helpers.
  - No `app.js` was reintroduced. No React / Vue / Vite / Node, local HTTP
    server, CDN, external JS/CSS/fonts, network requests, or browser storage
    were introduced.
- **Tests**:
  - Added `tests/test_project_rules_keyword_create.py` for API/service
    behavior: valid creation for normal and eligible-target projects,
    `排除规则` target eligibility per existing service semantics, full
    `project_id` / `keyword` invalid-input matrix, trim-before-create,
    unknown project / duplicate / service-exception collapse, no folder-rule
    / project / activity / assignment / session-note row changes, no
    conflict-preview / backfill / folder-create calls, cache invalidation,
    JSON-serializable payloads, stable success field types, and unchanged
    `set_project_rule_enabled` behavior.
  - Updated `tests/test_webview_project_rules_bridge.py` for the new bridge
    method: success payload shape, full invalid-input matrix → `操作无效`,
    `project_not_found` → `项目不存在`, `duplicate_rule` → `关键词规则已存在`,
    `operation_failed` / unknown code / exception → `新增关键词规则失败`,
    sensitive-text exclusion on every failure path, success never returns a
    full refreshed project list, the create path never calls any other
    Project Rules write API, stable success field types, JSON-serializable
    payloads, and unchanged `get_project_rules` / `set_project_rule_enabled`.
  - Updated `tests/webview/test_project_rules_static_contract.py` for the
    new form anchors, project selector / keyword input / submit button /
    empty hint, `App.rulesCreatingKeyword` state, the allowed
    `create_project_keyword_rule` bridge call, JS validation / trim /
    creating guard / `正在新增…` label, success-then-refresh /
    success-clears-input / failure-preserves-list-and-input, no raw
    exception reads, escape-helper usage, state isolation from the Phase 5B
    toggle saving state, stale-guard preservation, no storage / network,
    init binds the submit button, no `app.js`, and no forbidden handler
    tokens. The bridge-call forbidden-method check was switched to
    `callBridge("<method>"` string patterns so the allowed
    `create_project_keyword_rule` call is not falsely flagged by the
    `create_project` substring. The static button count assertion was
    relaxed to allow exactly one static button
    (`rules-keyword-create-submit`). The boundary-copy assertion was updated
    to match the new Phase 5C copy that mentions keyword creation.
  - Updated `tests/webview/test_statistics_static_contract.py` and
    `tests/webview/test_timeline_static_contract.py` so their Phase 5B
    boundary-copy assertions match the Phase 5C copy (which now references
    `启用/停用`, `新增关键词规则`, `编辑/删除`, and
    `冲突预览和回填将在后续阶段开放`).
- **Documentation**:
  - README, current-state, migration summary, and this history now mark
    Phase 5C as current, describe the keyword-rule-creation-only scope,
    preserve the Phase 5B / 5B.1 enable/disable path and its hardening, and
    restate all not-yet-open boundaries. Phase 4B / 4B.1 CSV export
    boundaries are preserved.
  - No DB schema change. No legacy Tkinter UI removal. No new dependency.
    No new frontend framework / network / browser storage.

## Phase 5C Not Implemented

Phase 5C does not implement and does not start:

- Project enable/disable in WebView;
- Project creation, editing, deletion, or archive in WebView;
- Folder rule creation, editing, or deletion in WebView;
- Keyword rule editing or deletion in WebView (Phase 5C only opens keyword
  rule creation);
- Folder rule conflict preview;
- Folder rule backfill;
- Automatic rules;
- Batch Project Rules operations;
- Settings / Privacy / Encrypted Backup WebView migration;
- Excel export;
- PDF export;
- Timesheet export or auto-submit;
- Folder opening or auto-open of exported files;
- DB schema changes;
- Legacy Tkinter UI removal;
- Tkinter fallback path;
- React / Vue / Vite / Node dependency;
- Local HTTP / FastAPI server;
- CDN / external JS / CSS / font / Google Fonts usage;
- `localStorage` / `sessionStorage` usage;
- Network requests;
- Any change to the existing Timeline, Statistics / CSV export, Overview,
  collector, privacy, encrypted backup, or database semantics.

## Phase 5C.1 Implemented Scope

Phase 5C.1 is the **Project Rules keyword creation hardening** phase. It is
a hardening-only / regression-only follow-up to Phase 5C. It does not open
any new Project Rules capability; it locks the Phase 5C keyword rule
creation write path so the behavior stays stable. Phase 5C remains the most
recent behavior-changing phase.

Implemented in Phase 5C.1:

- **API layer hardening** (`worktrace/api/rule_api.create_project_keyword_rule`):
  - Regression-locked `project_id` validation: real `int > 0`, rejecting
    `bool` / `float` / numeric string / `None` / list / dict / tuple / set /
    frozenset / zero / negative.
  - Regression-locked `keyword` validation: real `str`, rejecting `None` /
    `bool` / `int` / `float` / list / dict / tuple / set / frozenset, plus
    trim-then-empty rejection.
  - Regression-locked HTML / script-like keyword handling: the API saves the
    keyword as ordinary plain text; the success payload is JSON-serializable
    and never transforms or executes the content. Frontend rendering escape
    is locked by the static-contract escape-helper test.
  - Regression-locked duplicate detection (same `project_id` + same trimmed
    keyword, case-sensitive) returning the stable `duplicate_rule` code
    without creating a second row.
  - Regression-locked project eligibility reusing
    `project_api.list_rule_target_projects()` (archived / disabled / excluded
    projects rejected as `project_not_found`).
  - Regression-locked service exception collapse to `operation_failed`
    without surfacing traceback / SQL / raw exception / local path /
    window_title / clipboard / note.
  - Regression-locked no-side-effect guarantees: no folder rule / project /
    activity_log / activity_project_assignment / project_session_note rows
    touched; no conflict preview / backfill / folder create called; cache
    invalidation preserved; success and failure payloads JSON-serializable;
    existing `set_project_rule_enabled` not regressed.

- **Bridge layer hardening**
  (`worktrace/webview_ui.bridge.WebViewBridge.create_project_keyword_rule`):
  - Regression-locked bridge input validation: rejects bool-as-int
    `project_id`, non-positive `project_id`, non-string `keyword`, and
    whitespace-only `keyword` before any API call.
  - Hardened the bridge to forward the **trimmed** keyword to the API
    (behavior-neutral defense-in-depth: the API already trims, so observable
    behavior is unchanged).
  - Regression-locked success payload shape (`ok` / `rule.{kind, id,
    project_id, keyword, enabled}`) and stable Chinese failure messages
    (`操作无效` / `项目不存在` / `关键词规则已存在` / `新增关键词规则失败`).
  - Regression-locked that the success payload does not return a refreshed
    project list, does not surface backend error codes / traceback / SQL /
    path / window_title / clipboard / note, and does not call project
    create/edit/delete/enable-disable, folder create/edit/delete, keyword
    edit/delete, or conflict preview/backfill.
  - Regression-locked bridge import boundary (only `worktrace.api`) and
    that `get_project_rules` / `set_project_rule_enabled` are not regressed.

- **Frontend hardening** (`worktrace/webview_ui/js/rules.js`):
  - Regression-locked the creating guard (`App.rulesCreatingKeyword`),
    single-in-flight submit prevention, creating button label (`正在新增…`),
    and creating state clearing on success / failure / rejected-promise
    paths.
  - Regression-locked project id parse/validate, keyword trim/validate, and
    whitespace-only keyword rejection before any bridge call.
  - Regression-locked success path (clear input → refresh list → show
    success status) and failure path (preserve keyword input, preserve
    rendered list, do not clear selector).
  - Regression-locked catch path never reads `.message`; stable fallback
    text locked.
  - Regression-locked that the keyword create status uses `textContent`
    (HTML-safe), never `innerHTML`.
  - Regression-locked toggle/create state isolation
    (`rulesCreatingKeyword` vs `rulesSavingRuleKey`), stale response guard,
    selector in-flight guard, no duplicate static DOM ids, no
    localStorage/sessionStorage, no remote resource/CDN/Google Fonts, no
    `app.js`, script order, and packaging/static-resource contract.
  - Regression-locked that the Project Rules page has no Excel / PDF /
    timesheet / open-folder / auto-submit controls.

- **Documentation**: README, `current-state.md`, `ui-webview-migration.md`,
  and this file are updated to mark the current phase as 5C.1, clarify that
  Phase 5C is the most recent behavior-changing phase, clarify that Phase
  5C.1 is hardening-only / regression-only, restate the open capabilities
  (existing folder / keyword rule enable-disable; keyword rule creation on
  existing rule-target project), restate all not-yet-open boundaries,
  preserve Phase 4B / 4B.1 CSV export boundaries, and confirm no DB schema
  change. No legacy Tkinter runtime support is re-promised.

Phase 5C.1 did not modify `WorkTrace.spec`, resource loading, packaging
paths, or PyInstaller-related logic. The packaging static test
(`tests/test_webview_packaging.py`) and the `worktrace.webview_main` import
check were run and pass; the full PyInstaller build was not re-run because
no packaging behavior changed.

## Phase 5C.1 Not Implemented

Phase 5C.1 does not implement and does not start:

- Project enable/disable in WebView;
- Project creation, editing, deletion, or archive in WebView;
- Folder rule creation, editing, or deletion in WebView;
- Keyword rule editing or deletion in WebView (Phase 5C.1 only hardens the
  Phase 5C keyword rule creation path);
- Folder rule conflict preview;
- Folder rule backfill;
- Automatic rules;
- Batch Project Rules operations;
- Settings / Privacy / Encrypted Backup WebView migration;
- Excel export;
- PDF export;
- Timesheet export or auto-submit;
- Folder opening or auto-open of exported files;
- DB schema changes;
- Legacy Tkinter UI removal;
- Tkinter fallback path;
- React / Vue / Vite / Node dependency;
- Local HTTP / FastAPI server;
- CDN / external JS / CSS / font / Google Fonts usage;
- `localStorage` / `sessionStorage` usage;
- Network requests;
- Any change to the existing Timeline, Statistics / CSV export, Overview,
  collector, privacy, encrypted backup, or database semantics.

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

## Phase 5D Implemented Scope

Phase 5D is the **Project Rules keyword rule delete foundation** phase. It
opens one minimal new Project Rules write capability: deleting a single
existing keyword rule from the WebView Project Rules page, then refreshing
the list on success. It is the second new Project Rules write path beyond
the Phase 5B / 5B.1 existing folder / keyword rule enable/disable toggle
(after the Phase 5C keyword rule creation path), and it deliberately does
not open any other Project Rules write workflow. The write does not change
historical activity classification or schema.

Implemented in Phase 5D:

- **API layer** (`worktrace/api/rule_api.py`):
  - Added a narrow `delete_project_keyword_rule(rule_id)` facade for
    WebView writes. It deletes exactly one existing keyword rule and
    nothing else.
  - `rule_id` must be a real `int` and `> 0`; bool-as-int, `None`,
    numeric strings, floats, zero, negative ints, lists, dicts, tuples,
    sets, and frozensets are rejected with the stable `invalid_input`
    code.
  - The rule must exist and must be a keyword rule. A `rule_id` that
    points at a folder rule (or at an unknown id) returns the stable
    `not_found` code; the facade never deletes a folder rule and never
    reveals which table the id belongs to.
  - Raw service exceptions collapse to `operation_failed`. Tracebacks,
    SQL, raw exception text, paths, window titles, clipboard, and notes
    never cross the API boundary.
  - The facade delegates to the existing `rule_service.delete_rule` write
    path, preserving keyword rule cache invalidation and privacy exclude
    cache clearing. It does not call conflict preview, backfill, or any
    folder-rule write path, and does not touch `activity_log`,
    `activity_project_assignment`, `project_session_note`, folder rules,
    or project rows.
  - Success returns `{"ok": True, "rule": {"kind": "keyword", "id": int,
    "deleted": True}}`. The API does not return a refreshed Project Rules
    list (the frontend calls `get_project_rules` after success).
- **Bridge layer** (`worktrace/webview_ui/bridge.py`):
  - Added `delete_project_keyword_rule(rule_id)`.
  - Bridge validation mirrors the API: rejects bool-as-int `rule_id`,
    non-positive ids, non-int `rule_id` (numeric strings, floats, `None`,
    containers) before calling `rule_api`, returning `操作无效`.
  - Success returns the narrow `{"ok": True, "rule": {...}}` shape with
    coerced `int` field types.
  - Failure returns stable Chinese messages only: `操作无效`
    (`invalid_input`), `关键词规则不存在` (`not_found`),
    `删除关键词规则失败` (`operation_failed` and any unknown code /
    exception). Tracebacks, SQL, raw exception text, paths, window
    titles, clipboard, notes, backend error codes, and internal fields
    are never surfaced.
  - The bridge still imports only `worktrace.api` from the backend. It
    does not import services, db, collector, security, runtime, or
    config, and does not call any other Project Rules write API.
- **Frontend** (`worktrace/webview_ui/index.html`,
  `worktrace/webview_ui/js/core.js`, `worktrace/webview_ui/js/rules.js`,
  `worktrace/webview_ui/styles.css`):
  - Added a minimal per-keyword-row delete button with stable DOM
    attributes: `.rules-keyword-delete-button`,
    `data-rule-kind="keyword"`, and `data-rule-id="<int>"`. The button
    is rendered only on keyword rule rows; folder rule rows and project
    cards never render it.
  - Added `App.rulesDeletingRuleKey` state, separate from the Phase 5B
    `App.rulesSavingRuleKey` toggle state and the Phase 5C
    `App.rulesCreatingKeyword` create state, so the three write paths
    never pollute each other. Only one keyword delete may be in flight
    at a time.
  - The click handler (delegated on `#rules-list`) validates
    `data-rule-kind === "keyword"` and parses / validates `data-rule-id`
    (`parseInt` + `> 0` + round-trip string check) before calling
    `App.callBridge("delete_project_keyword_rule", ruleId)`. Malformed
    dataset values never call the bridge.
  - The handler requires a `window.confirm` with the stable text
    `确定删除这条关键词规则吗？删除后该关键词将不再用于自动归类。`.
    Cancellation does not call the bridge.
  - During deletion the active button shows `正在删除…` and repeats are
    blocked; toggle buttons are also disabled while any delete is in
    flight.
  - Success calls `App.loadProjectRules()` to refresh the list and shows
    a stable success status. Failure preserves the rendered list and
    shows a stable error status.
  - Catch paths do not read `err.message` / `error.message`; dynamic
    text is rendered through escaping / safe-text helpers.
  - The `App.rulesRequestToken` stale guard is preserved.
  - No `app.js` was reintroduced. No React / Vue / Vite / Node, local
    HTTP server, CDN, external JS/CSS/fonts, network requests, or
    browser storage were introduced.
  - The Project Rules page hint copy was updated to mention keyword
    deletion: `当前支持查看项目规则、启用/停用已有文件夹或关键词规则、新增关键词规则，并删除已有关键词规则。文件夹规则新增/删除、规则编辑、项目管理、冲突预览和回填将在后续阶段开放。`
- **CSS** (`worktrace/webview_ui/styles.css`):
  - Added a `.rules-keyword-delete-button` style block mirroring the
    existing toggle button visual style (same border / radius / padding)
    with a red text color to signal destructive intent, plus
    `:hover:not(:disabled)` and `:disabled` states. The style is scoped
    to the Project Rules page and does not affect Timeline / Statistics
    / Overview.
- **Tests**:
  - Added `tests/test_project_rules_keyword_delete.py` for API/service
    behavior: valid deletion for normal and `排除规则` projects,
    disabled-rule deletion, full `rule_id` invalid-input matrix,
    unknown-id / folder-rule-id → stable `not_found` (folder rule row
    preserved), service-exception collapse to `operation_failed`, no
    folder-rule / project / activity / assignment / session-note row
    changes, no conflict-preview / backfill / folder-delete calls,
    keyword rule cache invalidation, JSON-serializable payloads, stable
    success field types, and unchanged `create_project_keyword_rule` /
    `set_project_rule_enabled` behavior.
  - Updated `tests/test_webview_project_rules_bridge.py` for the new
    bridge method: success payload shape, full invalid-input matrix →
    `操作无效`, `not_found` → `关键词规则不存在`, `operation_failed` /
    unknown code / exception → `删除关键词规则失败`, sensitive-text
    exclusion on every failure path, success never returns a full
    refreshed project list, the delete path never calls any other
    Project Rules write API, stable success field types,
    JSON-serializable payloads, and unchanged `get_project_rules` /
    `set_project_rule_enabled` / `create_project_keyword_rule`.
  - Updated `tests/webview/test_project_rules_static_contract.py` for
    the new delete button anchors, `App.rulesDeletingRuleKey` state, the
    allowed `delete_project_keyword_rule` bridge call, JS validation /
    deleting guard / `正在删除…` label / confirmation text /
    cancellation path, success-then-refresh / failure-preserves-list,
    no raw exception reads, escape-helper usage, state isolation from
    the Phase 5B toggle saving state and the Phase 5C keyword creating
    state, stale-guard preservation, no storage / network, no
    `app.js`, no forbidden handler tokens, and no Excel / PDF /
    timesheet / open-folder / auto-submit controls.
  - Updated `tests/webview/test_statistics_static_contract.py` and
    `tests/webview/test_timeline_static_contract.py` so their Project
    Rules boundary-copy assertions match the Phase 5D copy (which now
    references `删除已有关键词规则` as supported and `编辑` as
    not-yet-open).
- **Documentation**:
  - README, current-state, migration summary, and this history now mark
    Phase 5D as current, describe the keyword-rule-deletion-only scope,
    preserve the Phase 5B / 5B.1 enable/disable path and its hardening,
    preserve the Phase 5C keyword creation path and the Phase 5C.1
    hardening, and restate all not-yet-open boundaries. Phase 4B / 4B.1
    CSV export boundaries are preserved.
  - No DB schema change. No legacy Tkinter UI removal. No new
    dependency. No new frontend framework / network / browser storage.

Phase 5D did not modify `WorkTrace.spec`, resource loading, packaging
paths, or PyInstaller-related logic. The packaging static test
(`tests/test_webview_packaging.py`) and the `worktrace.webview_main`
import check were run and pass; the full PyInstaller build was not
re-run because no packaging behavior changed.

## Phase 5D Not Implemented

Phase 5D does not implement and does not start:

- Project enable/disable in WebView;
- Project creation, editing, deletion, or archive in WebView;
- Folder rule creation, editing, or deletion in WebView;
- Keyword rule editing in WebView (Phase 5D only opens keyword rule
  deletion);
- Folder rule conflict preview;
- Folder rule backfill;
- Automatic rules;
- Batch Project Rules operations (including batch keyword delete);
- Settings / Privacy / Encrypted Backup WebView migration;
- Excel export;
- PDF export;
- Timesheet export or auto-submit;
- Folder opening or auto-open of exported files;
- DB schema changes;
- Legacy Tkinter UI removal;
- Tkinter fallback path;
- React / Vue / Vite / Node dependency;
- Local HTTP / FastAPI server;
- CDN / external JS / CSS / font / Google Fonts usage;
- `localStorage` / `sessionStorage` usage;
- Network requests;
- Any change to the existing Timeline, Statistics / CSV export, Overview,
  collector, privacy, encrypted backup, or database semantics.

## Phase 5D.1 Implemented Scope

Phase 5D.1 is the **Project Rules keyword deletion hardening** phase. It is
a hardening-only / regression-only follow-up to Phase 5D. It does not open
any new Project Rules capability; it locks the Phase 5D keyword rule
deletion write path so the behavior stays stable. Phase 5D remains the most
recent behavior-changing phase.

Implemented in Phase 5D.1:

- **API layer hardening** (`worktrace/api/rule_api.delete_project_keyword_rule`):
  - Regression-locked `rule_id` validation: real `int > 0`, rejecting
    `bool` / `float` / numeric string / `None` / list / dict / tuple / set
    / frozenset / zero / negative (the existing `type(rule_id) is not int`
    check already rejects `bool` because `type(True) is bool`).
  - Regression-locked keyword-only delete boundary: the API pre-checks
    `_rule_exists("keyword", rule_id)` and returns the stable `not_found`
    code for any id that does not resolve to a keyword rule, without
    touching the folder rule row.
  - Regression-locked that a folder-rule id is **not** deleted through the
    keyword delete path and the API returns the stable `not_found` code
    rather than leaking the folder-table detail.
  - Regression-locked that a second no-op delete (after the rule is already
    gone) returns `not_found` and is **not** treated as silent success.
  - Regression-locked that the delete path does not invoke the keyword
    `create_rule` or `set_rule_enabled` service paths.
  - Regression-locked that the delete path does not invoke folder delete,
    conflict preview, backfill, or any project write path.
  - Regression-locked service exception collapse to `operation_failed`
    without surfacing traceback / SQL / raw exception / local path /
    window_title / clipboard / note.
  - Regression-locked no-side-effect guarantees: no folder rule / project /
    activity_log / activity_project_assignment / project_session_note rows
    touched; existing keyword rule cache invalidation and
    `clear_exclude_rules_cache` semantics preserved; success and failure
    payloads JSON-serializable; existing `create_project_keyword_rule` and
    `set_project_rule_enabled` not regressed.

- **Bridge layer hardening**
  (`worktrace/webview_ui.bridge.WebViewBridge.delete_project_keyword_rule`):
  - Regression-locked bridge input validation: rejects bool-as-int
    `rule_id`, non-positive `rule_id`, non-int `rule_id`, and
    list / dict / tuple / set / frozenset `rule_id` before any API call.
  - Regression-locked success payload shape
    (`ok` / `rule.{kind="keyword", id, deleted=true}`) and stable Chinese
    failure messages (`操作无效` / `关键词规则不存在` / `删除关键词规则失败`).
  - Regression-locked that the bridge strips any extra API keys from the
    success payload so only `kind` / `id` / `deleted` surface to JS, never
    `project_id` / `keyword` text / `folder_path` / `traceback` / `sql` /
    `local path` / `window_title` / `clipboard` / `note`.
  - Regression-locked that the success payload does not return a refreshed
    project list, does not surface backend error codes / raw exception text,
    and does not call project create/edit/delete/enable-disable, folder
    create/edit/delete, keyword edit, or conflict preview/backfill.
  - Regression-locked bridge import boundary (only `worktrace.api`) and
    that `get_project_rules` / `set_project_rule_enabled` /
    `create_project_keyword_rule` are not regressed.

- **Frontend hardening** (`worktrace/webview_ui/js/rules.js`):
  - Regression-locked that the keyword delete button only appears on
    keyword rule rows (via `data-rule-kind="keyword"` event-delegation
    guard) and never on folder rule rows or project cards.
  - Regression-locked the deleting guard (`App.rulesDeletingRuleKey`),
    single-in-flight submit prevention, deleting button label
    (`正在删除…`), and deleting state clearing on success / failure /
    rejected-promise paths.
  - Regression-locked rule id parse/validate (`parseInt` + `> 0` guard)
    before any bridge call; malformed dataset does not call the bridge.
  - Regression-locked success path (refresh Project Rules list) and
    failure path (preserve rendered list, show stable Chinese fallback).
  - Regression-locked catch path never reads `.message`; stable fallback
    text locked.
  - Regression-locked delete state isolation from toggle saving state
    (`rulesDeletingRuleKey` vs `rulesSavingRuleKey`) and from keyword
    creating state (`rulesDeletingRuleKey` vs `rulesCreatingKeyword`).
  - Regression-locked stale response guard remains, no duplicate static
    DOM ids, no localStorage/sessionStorage, no remote resource/CDN/Google
    Fonts, no `app.js`, script order, and packaging/static-resource
    contract.
  - Regression-locked that the Project Rules page has no Excel / PDF /
    timesheet / open-folder / auto-submit controls, no folder
    create/delete controls, and no project management controls.

- **CSS hardening** (`worktrace/webview_ui/styles.css`):
  - Regression-locked that the `.rules-keyword-delete-button` class is
    defined and is scoped to the Project Rules page; it is not referenced
    by the Timeline / Statistics / Overview HTML sections.

- **Documentation**: README, `current-state.md`, `ui-webview-migration.md`,
  and this file are updated to mark the current phase as 5D.1, clarify that
  Phase 5D is the most recent behavior-changing phase, clarify that Phase
  5D.1 is hardening-only / regression-only, restate the open capabilities
  (existing folder / keyword rule enable-disable; keyword rule creation on
  existing rule-target project; keyword rule deletion), restate all
  not-yet-open boundaries, preserve Phase 4B / 4B.1 CSV export boundaries,
  and confirm no DB schema change. No legacy Tkinter runtime support is
  re-promised.

Phase 5D.1 did not modify `WorkTrace.spec`, resource loading, packaging
paths, or PyInstaller-related logic. The packaging static test
(`tests/test_webview_packaging.py`) and the `worktrace.webview_main` import
check were run and pass; the full PyInstaller build was not re-run because
no packaging behavior changed.

## Phase 5D.1 Not Implemented

Phase 5D.1 does not implement and does not start:

- Project enable/disable in WebView;
- Project creation, editing, deletion, or archive in WebView;
- Folder rule creation, editing, or deletion in WebView;
- Keyword rule editing in WebView (Phase 5D.1 only hardens the Phase 5D
  keyword rule deletion path);
- Folder rule conflict preview;
- Folder rule backfill;
- Automatic rules;
- Batch Project Rules operations (including batch keyword delete);
- Settings / Privacy / Encrypted Backup WebView migration;
- Excel export;
- PDF export;
- Timesheet export or auto-submit;
- Folder opening or auto-open of exported files;
- DB schema changes;
- Legacy Tkinter UI removal;
- Tkinter fallback path;
- React / Vue / Vite / Node dependency;
- Local HTTP / FastAPI server;
- CDN / external JS / CSS / font / Google Fonts usage;
- `localStorage` / `sessionStorage` usage;
- Network requests;
- Any change to the existing Timeline, Statistics / CSV export, Overview,
  collector, privacy, encrypted backup, or database semantics.

## Phase 5E Implemented Scope

Phase 5E is the **Project Rules folder rule CRUD foundation** phase. It opens
three new Project Rules folder rule write capabilities on an existing
rule-target project — creating one folder rule, editing an existing folder
rule, and deleting a single existing folder rule — then refreshing the list
on success. The API / bridge / frontend three layers are wired through the
stable `create_project_folder_rule` / `update_project_folder_rule` /
`delete_project_folder_rule` facade.

Implemented in Phase 5E:

- API facade in `worktrace/api/rule_api.py`:
  - `create_project_folder_rule(project_id, folder_path, recursive)`:
    validates `project_id` (true int, > 0, bool rejected), `folder_path`
    (true str, trim non-empty), and `recursive` (true bool); rejects None /
    float / numeric-string / container types; verifies the project exists and
    is a rule-target project (excludes `排除规则` / archived / disabled);
    delegates to `folder_rule_service.create_or_update_folder_rule`
    (create-or-update semantics on `normalized_folder_key`, always resets
    `enabled = 1`); returns `{"ok": True, "rule": {"kind": "folder", "id":
    <id>, "folder_path": <normalized>, "recursive": <bool>, "project_id":
    <id>}}` on success, or `{"ok": False, "error": "invalid_input" |
    "project_not_found" | "operation_failed"}` on failure. The success payload
    never exposes traceback / SQL / local scan path / window title / clipboard
    / note.
  - `update_project_folder_rule(rule_id, folder_path, recursive)`: validates
    `rule_id` (true int, > 0, bool rejected), `folder_path`, and `recursive`;
    resolves the row via the folder-only helper `_folder_rule_row(rule_id)`
    (keyword rule ids return None and produce `not_found` so the keyword rule
    is never modified); preserves the existing `project_id` (no cross-project
    move); returns `{"ok": True, "rule": {"kind": "folder", "id": <id>,
    "folder_path": <normalized>, "recursive": <bool>, "project_id": <id>}}`
    on success, or `{"ok": False, "error": "invalid_input" | "not_found" |
    "operation_failed"}` on failure.
  - `delete_project_folder_rule(rule_id)`: validates `rule_id`; resolves via
    `_folder_rule_row(rule_id)` (keyword rule ids return `not_found` so the
    keyword rule is never deleted); a second delete on the same id returns
    `not_found` (no silent success); returns `{"ok": True, "rule": {"kind":
    "folder", "id": <id>, "deleted": True}}` on success, or `{"ok": False,
    "error": "invalid_input" | "not_found" | "operation_failed"}` on failure.
  - All payloads are JSON-serializable and collapse any unexpected
    exception to `operation_failed` without leaking traceback / SQL / local
    path / window_title / clipboard / note.
  - Folder rule CRUD does not modify project rows, keyword rules,
    `activity_log`, `activity_project_assignment`, `project_session_note`,
    Timeline / Statistics / Export semantics, or the DB schema.

- Bridge methods in `worktrace/webview_ui/bridge.py`:
  - `create_project_folder_rule(project_id, folder_path, recursive)`,
    `update_project_folder_rule(rule_id, folder_path, recursive)`, and
    `delete_project_folder_rule(rule_id)`: each performs the same input
    validation as the API before delegating to `rule_api`; narrows the API
    payload to JS-essential fields only (strips any extra sensitive keys the
    API might add); maps stable error codes to stable Chinese messages
    (`invalid_input -> 操作无效`, `project_not_found -> 项目不存在或不可用`,
    `not_found -> 文件夹规则不存在`, `operation_failed -> 新增文件夹规则失败
    / 保存文件夹规则失败 / 删除文件夹规则失败`); collapses any unexpected
    exception to the same Chinese fallback without forwarding
    `exception.message` / `repr(exception)` / traceback / SQL / path /
    window_title / clipboard / note.
  - The bridge never returns a full refreshed project list; the frontend
    triggers `get_project_rules` separately on success.
  - Existing `get_project_rules` / `set_project_rule_enabled` /
    `create_project_keyword_rule` / `delete_project_keyword_rule` behavior
    is unchanged.
  - The bridge still imports `worktrace.api` only — it never imports
    `worktrace.services`, `worktrace.db`, `worktrace.collector`,
    `worktrace.security`, or `worktrace.runtime`.

- Frontend (`worktrace/webview_ui/js/rules.js` + `core.js` + `init.js` +
  `index.html`):
  - Create: a project selector + folder path input + recursive checkbox +
    submit button at the top of the Project Rules page; on submit it calls
    `create_project_folder_rule`, disables the submit button while saving,
    preserves the user input on failure, and calls `get_project_rules` on
    success to refresh the list.
  - Edit: each existing folder rule row renders an inline edit form (path
    input + recursive checkbox + save / cancel buttons) that calls
    `update_project_folder_rule` on save, disables its own buttons while
    saving, preserves the in-progress edit input on failure, and refreshes
    the list on success. Keyword rows do not render this form.
  - Delete: each existing folder rule row renders a delete button that
    requires `window.confirm`, calls `delete_project_folder_rule` (never
    `delete_project_keyword_rule`), shows a deleting state, preserves the
    rendered list on failure, and refreshes the list on success.
  - Independent state keys: `App.rulesCreatingFolder`,
    `App.rulesEditingFolderKey`, `App.rulesDeletingFolderKey` — kept
    separate from `App.rulesSavingRuleKey`, `App.rulesCreatingKeyword`,
    `App.rulesDeletingRuleKey`. Same-row write coordination disables the
    row's other write buttons while a write is in flight.
  - The global stale-response guard (`App.rulesRequestToken`) is preserved;
    a refresh response whose token no longer matches is dropped.
  - Catch paths never read `err.message` / `error.message` / `.toString` /
    raw backend payloads; failures fall back to the stable Chinese text the
    bridge returned, or to a hardcoded Chinese fallback.
  - No new DOM id duplicates; no `localStorage` / `sessionStorage`; no
    `fetch` / `XMLHttpRequest`; no external JS / CSS / CDN / Google Fonts;
    no `app.js` restoration; no Excel / PDF / timesheet / open-folder /
    auto-submit controls; no project management controls.

- CSS in `worktrace/webview_ui/styles.css`:
  - New `rules-folder-*` classes for the create form, project selector,
    folder path input, recursive checkbox, submit button, status text,
    inline edit form, save / cancel buttons, edit / delete buttons, and
    deleting / saving disabled states.
  - All `rules-folder-*` classes are scoped to the Project Rules page and
    do not touch Overview / Timeline / Statistics styles.
  - No external fonts or network resources are introduced; the existing
    page style is preserved.

- Tests:
  - New `tests/test_project_rules_folder_crud.py` covering API/service
    regression: create success / trim / non-recursive; excluded / archived /
    disabled project rejection; create-or-update semantics; invalid inputs
    (bool / None / string / float / list / dict / tuple / set / frozenset /
    zero / negative for `project_id`, `folder_path`, `recursive`);
    `project_not_found`; exception collapse; no side effects; JSON
    serializable; update success / preserves `project_id` / trims / invalid
    inputs / `not_found` / keyword isolation; delete success /
    second-time-`not_found` / keyword isolation / invalid inputs; cross-
    contamination locks (no keyword create / delete, no preview / backfill,
    no project modifications).
  - Extended `tests/test_webview_project_rules_bridge.py` covering create /
    update / delete input validation, success payload narrowing, sensitive
    text exclusion, error-code-to-Chinese mapping, unknown-code collapse,
    unknown-exception collapse, JSON-serializable payloads, trimmed path
    forwarding, extra-key stripping, never calling other write APIs, and
    regression locks for `get_project_rules` / `set_project_rule_enabled` /
    `create_project_keyword_rule` / `delete_project_keyword_rule`.
  - Extended `tests/webview/test_project_rules_static_contract.py`
    covering static DOM anchors, state variable declarations, bridge call
    strings, input validation guards, creating / editing / deleting button
    states, success / failure refresh paths, state isolation between
    folder create / edit / delete and keyword create / delete / toggle,
    same-row write coordination, no duplicate DOM ids, no browser storage,
    no remote resources / CDN / Google Fonts, no `app.js`, no Excel / PDF /
    timesheet / open-folder / auto-submit / project management controls,
    `rules-folder-*` CSS class existence and scoping, and packaging spec
    inclusion of `rules.js`.

- Documentation: `README.md`, `docs/current-state.md`,
  `docs/ui-webview-migration.md`, and this file now describe the current
  phase as 5E, list folder rule create / edit / delete as a supported
  Project Rules capability, and explicitly enumerate the still-unsupported
  Project Rules workflows.

Phase 5E does not modify `WorkTrace.spec`, resource loading, packaging
paths, or the entry point. The WebView packaging static test
(`tests/test_webview_packaging.py`) and the `worktrace.webview_main` import
check were run and pass; the full PyInstaller build was not re-run because
no packaging behavior changed.

## Phase 5E Not Implemented

Phase 5E does not implement and does not start:

- Folder rule conflict preview in WebView;
- Folder rule backfill in WebView;
- Automatic rules in WebView;
- Batch folder rule operations (including batch folder delete and batch
  folder edit);
- Batch Project Rules operations (including batch keyword delete);
- Project enable/disable in WebView;
- Project creation, editing, deletion, or archive in WebView;
- Keyword rule editing in WebView (Phase 5E only opens folder rule create /
  edit / delete);
- Project / folder-rule conflict preview, backfill, and automatic rule
  workflows;
- Settings / Privacy / Encrypted Backup WebView migration;
- Excel export;
- PDF export;
- Timesheet export or auto-submit;
- Folder opening or auto-open of exported files;
- DB schema changes;
- Legacy Tkinter UI removal;
- Tkinter fallback path;
- React / Vue / Vite / Node dependency;
- Local HTTP / FastAPI server;
- CDN / external JS / CSS / font / Google Fonts usage;
- `localStorage` / `sessionStorage` usage;
- Network requests;
- Any change to the existing Timeline, Statistics / CSV export, Overview,
  collector, privacy, encrypted backup, or database semantics.

## Phase 5E.1 Implemented Scope

Phase 5E.1 is the **Project Rules folder rule CRUD hardening** phase. It is
a regression-only / hardening-only follow-up to Phase 5E. It does not open
any new user-visible capability and does not enlarge the WebView Project
Rules behavior boundary. It only locks the Phase 5E folder rule
create / edit / delete write path so it is more robust across API /
service / bridge / frontend / static contract / docs layers.

Implemented in Phase 5E.1:

- API / service regression locks in
  `tests/test_project_rules_folder_crud.py`:
  - Normalized folder key collision on update: updating a folder rule's
    path to a normalized key already owned by another folder rule in the
    same project returns `{"ok": False, "error": "operation_failed"}`
    (IntegrityError is collapsed) and does not modify either rule.
  - Update-by-id semantics: `update_project_folder_rule` preserves the
    existing `rule_id`, `project_id`, and `enabled` state; changing the
    folder path or recursive flag never collapses into create-or-update
    merge semantics on a different rule.
  - Recursive-only update on the same normalized key follows the existing
    create-or-update semantics (updates `recursive` in place).
  - Sensitive-field exclusion: create / update / delete success payloads
    contain only the documented JS-essential fields and never expose
    traceback / SQL / local absolute path / window_title / clipboard /
    note / process metadata (key-set + substring regression locks).
  - Cache invalidation hooks: create and update invoke
    `invalidate_folder_rule_cache`, `clear_exclude_rules_cache`, and
    `request_rebuild_for_rule`; delete invokes
    `invalidate_folder_rule_cache`, `clear_exclude_rules_cache`, and
    `delete_index_for_rule`. Invalid input / `project_not_found` /
    `not_found` rejections do not invoke any cache hook.
  - `keyword rule id` passed to update / delete returns `not_found` and
    does not modify or delete the keyword rule.
  - All payloads remain JSON-serializable.

- Bridge regression locks in
  `tests/test_webview_project_rules_bridge.py`:
  - Consolidated bool-as-int rejection: `create_project_folder_rule`,
    `update_project_folder_rule`, and `delete_project_folder_rule` all
    reject `True` / `False` for `project_id` / `rule_id` with the stable
    Chinese `操作无效` message.
  - Consistent Chinese error mapping: `invalid_input -> 操作无效` across
    all three folder methods; `project_not_found` is unique to create;
    `not_found` is unique to update / delete; unknown codes collapse to
    the per-method fallback.
  - Bridge never forwards bool `project_id` / `rule_id` or non-bool
    `recursive` to the API layer.
  - Success payloads are JSON-serializable and contain only the
    JS-essential fields (no `error` key, no API-internal keys).
  - Failure payloads (invalid-input path and API-error path) are
    JSON-serializable.
  - Cross-pollution isolation: folder methods never call
    `create_project_keyword_rule` / `delete_project_keyword_rule` /
    `set_project_rule_enabled`, and the keyword / toggle methods never
    call the folder write APIs.
  - No traceback / SQL / local path / window_title / clipboard / note
    leak in any payload.

- Frontend static contract regression locks in
  `tests/webview/test_project_rules_static_contract.py`:
  - Folder edit cancel does not call any bridge method, clears the
    editing state via `setFolderEditing(null)`, and has an early-return
    guard when no folder edit is in flight.
  - Folder edit start sets the editing key to `"folder:<id>"` so the
    inline edit form renders for the correct row only.
  - `setFolderSaving` disables both the save and cancel buttons while a
    save is in flight.
  - The inline edit form input has `maxlength="512"`.
  - Additional `rules-folder-edit-*` CSS classes exist in `styles.css`
    and are scoped to the Project Rules page (not present in Overview /
    Timeline / Statistics sections).
  - `core.js`, `init.js`, and `rules.js` contain no `localStorage` /
    `sessionStorage`, no `fetch(` / `XMLHttpRequest`, no external URL /
    CDN / Google Fonts, and no ES module syntax (`import` / `export`).
  - The packaging spec (`WorkTrace.spec`) includes `core.js`, `init.js`,
    and `rules.js`.
  - Folder state variables (`rulesCreatingFolder`,
    `rulesEditingFolderKey`, `rulesDeletingFolderKey`) are declared
    exactly once in `core.js`.
  - Folder create / edit / delete handlers do not use `.innerHTML`.
  - Folder edit save failure preserves the rendered list; success clears
    the editing state.
  - `bindProjectRuleFolderEvents` uses the `data-rules-folder-bound`
    idempotency pattern.

- Documentation: `README.md`, `docs/current-state.md`,
  `docs/ui-webview-migration.md`, and this file now describe the current
  phase as 5E.1 and explicitly note that 5E.1 is hardening-only /
  regression-only.

Phase 5E.1 does not modify `WorkTrace.spec` resource list (it only adds a
regression lock verifying the existing entries), `worktrace/api/rule_api.py`,
`worktrace/services/folder_rule_service.py`,
`worktrace/webview_ui/bridge.py`, `worktrace/webview_ui/js/*.js`,
`worktrace/webview_ui/index.html`, or `worktrace/webview_ui/styles.css`.
No runtime behavior changed. The WebView packaging static test
(`tests/test_webview_packaging.py`) and the `worktrace.webview_main` import
check were run and pass; the full PyInstaller build was not re-run because
no packaging or runtime behavior changed.

## Phase 5E.1 Not Implemented

Phase 5E.1 does not implement and does not start:

- Any new user-visible Project Rules capability;
- Folder rule conflict preview in WebView;
- Folder rule backfill in WebView;
- Automatic rules in WebView;
- Batch folder rule operations (including batch folder delete and batch
  folder edit);
- Batch Project Rules operations (including batch keyword delete);
- Project enable/disable in WebView;
- Project creation, editing, deletion, or archive in WebView;
- Keyword rule editing in WebView;
- Settings / Privacy / Encrypted Backup WebView migration;
- Excel export;
- PDF export;
- Timesheet export or auto-submit;
- Folder opening or auto-open of exported files;
- DB schema changes;
- Legacy Tkinter UI removal;
- Tkinter fallback path;
- React / Vue / Vite / Node dependency;
- Local HTTP / FastAPI server;
- CDN / external JS / CSS / font / Google Fonts usage;
- `localStorage` / `sessionStorage` usage;
- Network requests;
- Any change to the existing Timeline, Statistics / CSV export, Overview,
  collector, privacy, encrypted backup, or database semantics.

## Phase 5F Implemented Scope

Phase 5F is the **Project Rules keyword rule edit foundation + in-phase
hardening** phase. It opens one new user-visible Project Rules capability
and ships the hardening regression locks in the same phase rather than
splitting into a separate 5F.1.

Implemented in Phase 5F:

- New user-visible capability: editing the keyword text of a single
  existing keyword rule via an inline edit form on the keyword rule row,
  then refreshing the Project Rules list on success. The edit form
  contains a keyword text input (`maxlength="200"`), a "保存" button,
  and a "取消" button. The toggle and delete buttons stay disabled while
  keyword edit / save is in flight so the write paths cannot pollute
  each other.
- Service layer (`worktrace/services/rule_service.py`):
  - `update_rule(rule_id, keyword)` trims the keyword, raises
    `ValueError` on empty, updates only `pattern` and `updated_at` on
    `project_rule` rows where `id = rule_id` and `rule_type = 'keyword'`,
    and invokes `invalidate_keyword_rule_cache()` +
    `privacy_service.clear_exclude_rules_cache()` on success. It does
    not modify `project_id` / `enabled` / `created_by` / `created_at`
    and introduces no schema change.
- API layer (`worktrace/api/rule_api.py`):
  - `update_project_keyword_rule(rule_id, keyword)` with strict type
    validation (`type(rule_id) is int` excluding bool, `> 0`;
    `type(keyword) is str`, trimmed non-empty), stable error codes
    (`invalid_input` / `not_found` / `duplicate_rule` /
    `operation_failed`), duplicate check scoped to the same project and
    excluding the rule being updated (updating to its own current
    keyword succeeds), folder-rule-id returns `not_found` without
    modifying the folder rule, narrow success payload
    (`{"ok": True, "rule": {"kind": "keyword", "id": int, "project_id":
    int, "keyword": str, "enabled": bool}}`), unexpected exceptions
    collapsed to `operation_failed`, no traceback / SQL / path /
    window_title / clipboard / note leak. Cache hooks fire only on the
    success path. Exported via `__all__`.
- Bridge layer (`worktrace/webview_ui/bridge.py`):
  - `update_project_keyword_rule(rule_id, keyword)` bridge method with
    strict type validation (bool-as-int rejected, non-positive rule_id
    rejected, non-string / empty / whitespace keyword rejected),
    forwards the trimmed keyword to the API, maps the four stable error
    codes to Chinese via `_PROJECT_RULE_UPDATE_MESSAGES` (unknown codes
    collapse to "保存关键词规则失败"), returns a narrow payload with
    only `ok` / `rule.kind` / `rule.id` / `rule.project_id` /
    `rule.keyword` / `rule.enabled`, never exposes traceback / SQL /
    path / window_title / clipboard / note, and never imports
    services/db/collector/runtime/config. It does not affect
    `create_project_keyword_rule`, `delete_project_keyword_rule`,
    `set_project_rule_enabled`, or folder CRUD behavior.
- Frontend (`worktrace/webview_ui/js/core.js`,
  `worktrace/webview_ui/js/rules.js`,
  `worktrace/webview_ui/index.html`,
  `worktrace/webview_ui/styles.css`):
  - Two new state variables `App.rulesEditingKeywordKey` and
    `App.rulesUpdatingKeywordKey`, independent of all other write-path
    states (rulesSavingRuleKey / rulesCreatingKeyword /
    rulesDeletingRuleKey / rulesCreatingFolder / rulesEditingFolderKey /
    rulesDeletingFolderKey).
  - Keyword rows render an "编辑" button only when `kind === "keyword"`
    and `ruleId` is valid; folder rows never get a keyword edit button.
  - Clicking the edit button sets `rulesEditingKeywordKey` to
    `"keyword:<id>"` and re-renders the row into an inline edit form.
  - Save trims the input, rejects empty client-side, calls
    `update_project_keyword_rule`, clears editing + saving state and
    refreshes the list on success, preserves the input and editing
    state on failure, shows "正在保存…" and disables save/cancel
    while saving.
  - Cancel does not call the bridge; clears editing state and
    re-renders from cached data.
  - Event delegation via `#rules-list` with a
    `data-rules-keyword-edit-bound` idempotency guard; bound in both
    `showProjectRules` and `rerenderProjectRulesList`.
  - New CSS classes `.rules-keyword-edit-button`,
    `.rules-keyword-edit-form`, `.rules-keyword-edit-input`,
    `.rules-keyword-edit-save`, `.rules-keyword-edit-cancel` scoped to
    the Project Rules page (not referenced by Overview / Timeline /
    Statistics sections).
  - `index.html` boundary copy updated: "编辑已有关键词规则" added to
    the supported capabilities list; the "关键词规则编辑将在后续阶段
    开放" wording removed.
- API / service regression locks in
  `tests/test_project_rules_keyword_edit.py`: valid update, trim,
  preserve `rule_id` / `project_id` / `enabled` / `created_by` /
  `created_at`, input validation (bool / None / str / float / list /
  dict / tuple / set / frozenset / zero / negative rule_id, non-string
  keyword, whitespace-only keyword), missing id `not_found`, folder
  rule id `not_found` without modifying the folder rule, duplicate in
  same project `duplicate_rule`, same keyword in different project
  allowed, updating to own current keyword succeeds, unexpected
  exception collapses to `operation_failed`, cache hooks fire only on
  success, JSON-serializable payloads, sensitive-metadata exclusion,
  no side effects on folder rules / project table / enabled /
  created_by, regression locks for existing create/delete/toggle.
- Bridge regression locks in
  `tests/test_webview_project_rules_bridge.py`: bool-as-int rejection,
  non-int / non-positive rule_id rejection, non-string / empty /
  whitespace keyword rejection, trimmed keyword forwarded, error code
  mappings (all four codes + unknown collapse), exception collapse,
  narrow success payload, failure payload JSON-serializable, no
  sensitive-text leak, update keyword does not call other write APIs,
  other write APIs do not call update keyword, bool rule_id not
  forwarded to API.
- Frontend static contract regression locks in
  `tests/webview/test_project_rules_static_contract.py`: keyword edit
  button only on keyword rows, folder rows have no keyword edit
  button, edit start sets `"keyword:<id>"` key, cancel does not call
  bridge, save calls `update_project_keyword_rule`, save trims input,
  empty rejected client-side, save failure preserves editing state /
  input, save success clears editing state and reloads Project Rules,
  saving disables save and cancel buttons, input `maxlength="200"`,
  CSS classes exist and are Project Rules scoped, handlers do not read
  `.message`, no `fetch` / `XMLHttpRequest` / `localStorage` /
  `sessionStorage`, classic scripts (no `import` / `export`), no new
  external URLs / CDN / Google Fonts, state variables declared exactly
  once in `core.js`, event binding idempotent.
- Affected runner mapping (`scripts/run_affected_tests.py`):
  `tests/test_project_rules_keyword_edit.py` added to the Project
  Rules API / service / UI rule and the DB / schema rule so changes to
  `rule_api.py` / `rule_service.py` / `rules.js` / `db.py` / `schema.sql`
  run the new test file.
- Documentation: `README.md`, `docs/current-state.md`,
  `docs/ui-webview-migration.md`, and this file now describe the
  current phase as 5F and explicitly note that 5F ships the in-phase
  hardening regression locks rather than splitting into a separate
  5F.1.

Phase 5F does not modify `WorkTrace.spec` resource list (it only adds a
regression lock verifying the existing entries), `worktrace/db.py`,
`worktrace/schema.sql`, or any collector / privacy / encrypted backup /
statistics / export / timeline code. No DB schema change. The WebView
packaging static test (`tests/test_webview_packaging.py`) and the
`worktrace.webview_main` import check were run and pass; the full
PyInstaller build was not re-run because no packaging or runtime
behavior changed.

## Phase 5F Not Implemented

Phase 5F does not implement and does not start:

- Any new user-visible Project Rules capability other than editing the
  keyword text of a single existing keyword rule;
- Batch keyword edit;
- Batch keyword delete;
- Batch folder edit / delete;
- Folder rule conflict preview in WebView;
- Folder rule backfill in WebView;
- Automatic rules in WebView;
- Project enable/disable in WebView;
- Project creation, editing, deletion, or archive in WebView;
- Settings / Privacy / Encrypted Backup WebView migration;
- Excel export;
- PDF export;
- Timesheet export or auto-submit;
- Folder opening or auto-open of exported files;
- DB schema changes;
- Legacy Tkinter UI removal;
- Tkinter fallback path;
- React / Vue / Vite / Node dependency;
- Local HTTP / FastAPI server;
- CDN / external JS / CSS / font / Google Fonts usage;
- `localStorage` / `sessionStorage` usage;
- Network requests;
- Any change to the existing Timeline, Statistics / CSV export, Overview,
  collector, privacy, encrypted backup, or database semantics.

## Phase 5G Implemented Scope

Phase 5G is the **Project lifecycle foundation + in-phase hardening**
phase. It opens four project-level Project Rules write capabilities on
existing user projects and ships the hardening regression locks in the
same phase rather than splitting into a separate 5G.1.

Implemented in Phase 5G:

- New user-visible capabilities (all four only operate on existing user
  projects; system / special projects are always rejected):
  - Creating a user project via a top-of-page "新增项目" form with a
    name input (`maxlength="100"`) and a description input
    (`maxlength="500"`), then refreshing the Project Rules list on
    success.
  - Editing an existing user project's name / description via an inline
    edit form rendered in place of the project action buttons, then
    refreshing the list on success.
  - Enabling / disabling an existing user project via a toggle button
    on the project card, then refreshing the list on success.
  - Archiving an existing user project via an archive button on the
    project card (with a `confirm` confirmation), then refreshing the
    list on success.
  - System / special projects (`created_by == "system"`, `未归类`,
    `排除规则`) never render the edit / toggle / archive buttons. The
    read projection exposes display-safe `editable` / `can_toggle` /
    `can_archive` / `is_system` flags so the frontend can decide
    visibility without ever seeing the raw `created_by` value.
- Service layer (`worktrace/services/project_service.py`):
  - `archive_project(project_id)` now triggers the same three cache
    invalidation hooks as `set_project_enabled`:
    `invalidate_folder_rule_cache()` +
    `invalidate_keyword_rule_cache()` +
    `privacy_service.clear_exclude_rules_cache()`. Archive only sets
    `is_archived = 1` and `updated_at`; it does not physically delete
    the project, its folder rules, its keyword rules, its activity
    assignments, or its session notes.
  - `create_project`, `update_project`, `set_project_enabled` are
    reused unchanged. No schema change, no new helper.
- API layer (`worktrace/api/project_api.py`):
  - Four narrow facades: `create_project_for_rules(name, description="")`,
    `update_project_for_rules(project_id, name, description="")`,
    `set_project_enabled_for_rules(project_id, enabled)`,
    `archive_project_for_rules(project_id)`. The `_for_rules` suffix
    keeps Project lifecycle separate from Rule lifecycle in
    `rule_api.py`.
  - Strict type validation: `type(project_id) is int` excluding bool
    and `> 0`; `type(enabled) is bool`; `type(name) is str` with trim
    and non-empty; `type(description) is str` (empty allowed, trimmed
    on save).
  - Stable error codes: `invalid_input` / `not_found` / `system_project`
    / `duplicate_project` / `operation_failed`. System / special
    projects (`created_by == "system"`, `未归类`, `排除规则`) are
    rejected for all four writes; enabling `排除规则` is never allowed.
  - Duplicate-name check on create / update (trim-aware exact match)
    plus SQLite `IntegrityError` collapse to `duplicate_project` for
    the race condition. Unexpected exceptions collapse to
    `operation_failed`.
  - Narrow success payload:
    `{"ok": True, "project": {"id": int, "name": str, "description":
    str, "enabled": bool, "archived": bool}}`. No `created_by` /
    `created_at` / `updated_at` / raw row / traceback / SQL / path /
    window_title / clipboard / note leak.
  - `get_project_rules` read projection now includes display-safe
    `is_system` / `editable` / `can_toggle` / `can_archive` flags.
- Bridge layer (`worktrace/webview_ui/bridge.py`):
  - Four bridge methods: `create_project_for_rules`,
    `update_project_for_rules`, `set_project_enabled_for_rules`,
    `archive_project_for_rules`. They only call
    `worktrace.api.project_api`; they never import services / db /
    collector / runtime / config.
  - Strict type validation at the bridge too (bool-as-int rejected,
    non-int / non-positive project_id rejected, non-bool enabled
    rejected, non-string / empty / whitespace name rejected,
    non-string description rejected). Trimmed name / description are
    forwarded to the API.
  - Stable Chinese error mapping via four dedicated message maps
    (`_PROJECT_LIFECYCLE_CREATE_MESSAGES` /
    `_PROJECT_LIFECYCLE_UPDATE_MESSAGES` /
    `_PROJECT_LIFECYCLE_TOGGLE_MESSAGES` /
    `_PROJECT_LIFECYCLE_ARCHIVE_MESSAGES`); unknown codes collapse to
    a per-write Chinese message (新增项目失败 / 保存项目失败 /
    更新项目状态失败 / 归档项目失败). No `.message` reads, no
    traceback / SQL / path / window_title / clipboard / note leak.
  - Narrow success payload mirrors the API payload. The bridge never
    exposes `delete_project` and never calls keyword / folder rule
    write APIs.
- Frontend (`worktrace/webview_ui/js/core.js`,
  `worktrace/webview_ui/js/rules.js`,
  `worktrace/webview_ui/js/init.js`,
  `worktrace/webview_ui/index.html`):
  - Five new state variables in `core.js`:
    `App.rulesCreatingProject`, `App.rulesEditingProjectId`,
    `App.rulesUpdatingProjectId`, `App.rulesTogglingProjectId`,
    `App.rulesArchivingProjectId`. Independent of all keyword / folder
    rule write states.
  - Top-of-page "新增项目" form (`#rules-project-create-submit`) bound
    in `init.js` (same pattern as keyword / folder create submit).
  - Project edit / toggle / archive buttons render only on user
    projects (`editable && projectId`); system / special projects
    never get these buttons.
  - Inline edit form replaces the action buttons while
    `rulesEditingProjectId === projectId`; save trims, rejects empty
    client-side, calls `update_project_for_rules`, clears editing +
    saving state and refreshes on success, preserves input and
    editing state on failure. Cancel does not call the bridge.
  - Toggle and archive use `confirm` before calling the bridge; both
    refresh the list on success and preserve state on failure.
  - Event delegation on `#rules-list` with a
    `data-rules-project-lifecycle-bound` idempotency guard, mirroring
    the keyword edit pattern.
  - Project lifecycle write in-flight disables all project lifecycle
    buttons on every card so create / edit / toggle / archive cannot
    pollute each other.
  - No `fetch` / `XMLHttpRequest` / `localStorage` / `sessionStorage`
    / ES module / external URL / new dependency.
- API / service regression locks in
  `tests/test_project_rules_project_lifecycle.py`: create success +
  trim, create rejects bool / non-str / empty / whitespace, create
  duplicate name, update success preserves id / enabled / is_archived,
  update rejects bool / non-int / non-positive / non-str / empty,
  update not_found, update system project rejected, update duplicate
  name rejected, set enabled success true / false, set enabled rejects
  bool-as-int project_id / non-bool enabled, set enabled not_found,
  set enabled system / special project rejected (especially
  `排除规则`), archive success sets is_archived without deleting
  project / folder rules / keyword rules / activity / assignment /
  session_note rows, archive not_found / system project rejected,
  invalid / not_found / system / duplicate rejection do not trigger
  cache hooks, success triggers the three cache hooks, operation
  exception collapse, payload JSON serializable, payload contains no
  traceback / SQL / window_title / clipboard / note / created_by /
  created_at / updated_at / raw row, existing keyword / folder rule
  CRUD still works, `get_project_rules` payload includes display-safe
  flags.
- Bridge regression locks in
  `tests/test_webview_project_rules_bridge.py`: four bridge methods'
  input validation, Chinese error code mapping, trimmed forwarding,
  bool-as-int not forwarded to API, no cross-API calls (project
  create / edit / toggle / archive never call keyword / folder rule
  APIs), `delete_project` never exposed, narrow payload +
  JSON-serializable, unknown exception collapse, no sensitive-string
  leak, `get_project_rules` payload includes display-safe lifecycle
  flags.
- Frontend static contract regression locks in
  `tests/webview/test_project_rules_static_contract.py`: project
  create form DOM anchors, project edit / toggle / archive buttons
  only on user projects, inline project edit form, save calls bridge
  + trim + empty reject, success refresh, failure preserve input /
  state, cancel does not call bridge, confirm archive, project
  lifecycle state variables declared and declared once, CSS classes
  scoped to Project Rules, no `.message` / no `fetch` / no storage /
  no import / export / no external URL, `init.js` binds only project
  create submit (lifecycle handlers use event delegation), packaging
  spec unchanged, no `app.js`, no forbidden handler tokens.
- Affected runner mapping (`scripts/run_affected_tests.py`):
  `tests/test_project_rules_project_lifecycle.py` added to the
  Project Rules API / service / UI rule (section C) and the DB /
  schema / migrations broad rule (section F) so changes to
  `project_api.py` / `project_service.py` / `rules.js` / `db.py` /
  `schema.sql` run the new test file.
- Documentation: `README.md`, `docs/current-state.md`,
  `docs/ui-webview-migration.md`, and this file now describe the
  current phase as 5G and explicitly note that 5G ships the in-phase
  hardening regression locks rather than splitting into a separate
  5G.1.

Phase 5G does not modify `WorkTrace.spec` resource list, `worktrace/db.py`,
`worktrace/schema.sql`, or any collector / privacy / encrypted backup /
statistics / export / timeline code. No DB schema change. The WebView
packaging static test (`tests/test_webview_packaging.py`) and the
`worktrace.webview_main` import check were run and pass; the full
PyInstaller build was not re-run because no packaging or runtime
behavior changed.

## Phase 5G Not Implemented

Phase 5G does not implement and does not start:

- Hard delete project (Phase 5G never exposes
  `project_service.delete_project` to the WebView bridge);
- Project restore (un-archive) in WebView;
- Batch project create / edit / toggle / archive;
- Batch keyword edit / delete;
- Batch folder edit / delete;
- Folder rule conflict preview in WebView;
- Folder rule backfill in WebView;
- Automatic rules in WebView;
- Settings / Privacy / Encrypted Backup WebView migration;
- Excel export;
- PDF export;
- Timesheet export or auto-submit;
- Folder opening or auto-open of exported files;
- DB schema changes;
- Legacy Tkinter UI removal;
- Tkinter fallback path;
- React / Vue / Vite / Node dependency;
- Local HTTP / FastAPI server;
- CDN / external JS / CSS / font / Google Fonts usage;
- `localStorage` / `sessionStorage` usage;
- Network requests;
- Any change to the existing Timeline, Statistics / CSV export, Overview,
  collector, privacy, encrypted backup, or database semantics.

## Phase 5H Implemented Scope

Phase 5H is the **Rule impact preview + safe single-rule backfill
foundation + in-phase hardening** phase. It opens single-rule impact
preview and explicit safe single-rule backfill for folder / keyword rules
on the Project Rules page and ships the hardening regression locks in the
same phase rather than splitting into a separate 5H.1.

Implemented in Phase 5H:

- New user-visible capabilities:
  - Single-rule impact preview for folder rules and keyword rules. The
    preview returns display-safe counts (match count, would-update count,
    manual-record skip count, hidden / deleted / in-progress / non-normal
    skip count) plus up to 20 display-safe sample rows. No raw window
    title, file path, or note is exposed.
  - Explicit safe single-rule backfill for folder rules and keyword rules.
    Backfill is capped at 100 updates per call. Backfill does NOT
    overwrite manual records (`manual_override=1` or `is_manual=1` are
    skipped). Backfill skips hidden / deleted / in-progress / non-normal
    activities. `too_many_matches` returns a stable error code and writes
    nothing.
- Service layer (`worktrace/services/rule_impact_service.py` — new file):
  - Encapsulates impact preview + safe backfill for folder / keyword
    rules. Reuses the existing folder / keyword rule match helpers; no
    new DB schema, no new table, no new column.
  - Preview returns display-safe counts + ≤ 20 sample rows; backfill is
    capped at 100 updates per call and skips manual / hidden / deleted /
    in-progress / non-normal activities.
- API layer (`worktrace/api/rule_api.py`):
  - Two new facades: `preview_project_rule_impact(rule_type, rule_id)` and
    `backfill_project_rule(rule_type, rule_id)`. Strict type validation
    on `rule_type` (folder / keyword) and `rule_id` (int, > 0).
  - Stable error codes: `invalid_input` / `not_found` / `too_many_matches`
    / `operation_failed`. `too_many_matches` returns the stable code and
    writes nothing.
  - Narrow display-safe payload: counts + ≤ 20 sample rows; no raw window
    title / file path / note / traceback / SQL leak.
- Bridge layer (`worktrace/webview_ui/bridge_rules.py`):
  - Two new bridge methods: `preview_project_rule_impact` and
    `backfill_project_rule`. They only call `worktrace.api.rule_api`; they
    never import services / db / collector / runtime / config.
  - Strict type validation at the bridge too. Stable Chinese error
    mapping; unknown codes collapse to a per-action Chinese message. No
    `.message` reads, no traceback / SQL / path / window_title /
    clipboard / note leak.
- Frontend (`worktrace/webview_ui/js/rules_render.js`,
  `worktrace/webview_ui/js/rules_rule_actions.js`,
  `worktrace/webview_ui/js/core.js`,
  `worktrace/webview_ui/index.html`,
  `worktrace/webview_ui/styles.css`):
  - Impact buttons rendered per rule in `rules_render.js`; handlers in
    `rules_rule_actions.js`; preview / backfill panel in `index.html`;
    CSS in `styles.css`.
  - New state variables in `core.js` for preview / backfill in-flight
    state, isolated from existing keyword / folder / project lifecycle
    write states.
  - Backfill uses `confirm` before calling the bridge; preview and
    backfill refresh / reset the panel on success and preserve state on
    failure.
  - No `fetch` / `XMLHttpRequest` / `localStorage` / `sessionStorage`
    / ES module / external URL / new dependency / new JS file.
- Tests:
  - New `tests/test_project_rules_rule_impact.py` covering service / API /
    bridge regression locks: preview counts + sample rows, display-safe
    payload, backfill cap of 100, manual records preserved, hidden /
    deleted / in-progress / non-normal skipped, `too_many_matches`
    returns stable code and writes nothing, invalid / not_found paths,
    no sensitive-string leak, JSON-serializable payload.
  - Extended bridge tests in `tests/test_webview_project_rules_bridge.py`
    and static contract tests in
    `tests/webview/test_project_rules_static_contract.py` for the two new
    bridge methods, impact buttons, panel anchors, state variable
    declarations, CSS scoping, and no-forbidden-tokens.
- Affected runner mapping (`scripts/run_affected_tests.py`):
  - New C7 section for `rule_impact_service.py` mapping changes to
    `rule_impact_service.py` / `rule_api.py` / `bridge_rules.py` /
    `rules_render.js` / `rules_rule_actions.js` to the new
    `tests/test_project_rules_rule_impact.py` plus the extended bridge /
    static contract tests.
- Documentation: `README.md`, `docs/current-state.md`,
  `docs/ui-webview-migration.md`, and this file now describe the current
  phase as 5H and explicitly note that 5H ships single-rule impact
  preview + safe single-rule backfill (folder / keyword), not the raw
  folder-rule conflict preview / raw / batch backfill.

Phase 5H does not modify `WorkTrace.spec` resource list, `worktrace/db.py`,
`worktrace/schema.sql`, or any collector / privacy / encrypted backup /
statistics / export / timeline code. No DB schema change. No new
dependency. No new JS file. The WebView packaging static test
(`tests/test_webview_packaging.py`) and the `worktrace.webview_main`
import check were run and pass; the full PyInstaller build was not re-run
because no packaging or runtime behavior changed.

## Phase 5H Not Implemented

Phase 5H does not implement and does not start:

- Automatic rules (deferred to 5I);
- Batch Project Rules operations (deferred to 5I);
- Raw folder-rule conflict preview in WebView (the raw
  `folder_rule_service.preview_folder_rule_conflicts` is NOT exposed to
  WebView; 5H ships a separate display-safe rule impact preview facade);
- Raw / batch folder-rule backfill (5H ships only safe single-rule
  backfill, capped at 100 updates per call);
- Hard delete project (deferred);
- Project restore (un-archive) in WebView (deferred);
- Settings / Privacy / Encrypted Backup WebView migration;
- Excel / PDF / timesheet export or auto-submit;
- Folder opening or auto-open of exported files;
- DB schema changes;
- Legacy Tkinter UI removal;
- Tkinter fallback path;
- React / Vue / Vite / Node dependency;
- Local HTTP / FastAPI server;
- CDN / external JS / CSS / font / Google Fonts usage;
- `localStorage` / `sessionStorage` usage;
- Network requests;
- Any change to the existing Timeline, Statistics / CSV export, Overview,
  collector, privacy, encrypted backup, or database semantics.

## Phase 5I Implemented Scope

Phase 5I is the **Automatic rules + selected-rule batch operations
foundation** phase. It makes enabled folder / keyword Project Rules apply
automatically to newly produced / just-closed eligible activities, and it
opens selected-rule batch preview / apply / enable / disable on the Project
Rules page. Both features are foundation-grade: they reuse the existing
folder / keyword matching semantics (no second divergent matcher), enforce
strict validation and transactional safety, and ship hardening regression
locks in the same phase.

Implemented in Phase 5I:

- Automatic rules foundation:
  - Enabled folder / keyword rules now apply automatically to activities
    through the existing `finalize_created_activity` →
    `project_inference_service.process_new_activity` →
    `assign_project_for_activity` path. No new matcher, no new table, no
    new column.
  - Deterministic priority: folder rules before keyword rules; within the
    same kind, by rule id ascending; first match wins.
  - Writes `auto_classified=1`, `source=folder_rule` / `keyword_rule`,
    `confidence` 85 (folder) / 80 (keyword), `is_manual=0`. Automatic
    application never sets `manual_override=1`.
  - Skip guards (automatic-only, in `process_new_activity`):
    `manual_override=1`, `is_manual=1`, hidden, deleted, in-progress
    (`end_time IS NULL`), non-normal activities, already-target activities,
    disabled rules, disabled / archived / excluded target projects.
  - Archived-project filtering: `is_archived = 0` added to both
    `_enabled_keyword_rules` and `_enabled_folder_rules` SQL so archived
    projects (which keep `enabled = 1` after archiving) no longer match
    rules.
  - Skip-guard placement: hidden / deleted / in-progress guards live in
    `process_new_activity` (the automatic-only entry point), NOT in
    `assign_project_for_activity` (the general-purpose function used by
    manual reclassification, single-rule backfill, and batch apply). This
    keeps existing manual-path tests intact while meeting the automatic
    contract.
  - `worktrace/services/rule_automation_service.py` is a thin documented
    facade that delegates to `process_new_activity` so the automatic path
    can be guarded without affecting manual reclassification.
- Selected-rule batch operations foundation:
  - Four operations: batch preview impact, batch apply to history, batch
    enable, batch disable.
  - `rules` input: a list of `{"rule_type": "folder"|"keyword",
    "rule_id": positive int}`. Validation rejects non-list / empty /
    bool-as-int / negative / zero ids, dedupes (first occurrence wins),
    caps at 20 rules (`too_many_rules`), and returns `not_found` for any
    missing rule.
  - Batch apply: capped at 100 total updates (`too_many_matches` writes
    nothing), first-rule-wins on collisions, all-or-nothing transaction
    with rowcount guard rollback. Skips manual / hidden / deleted /
    in-progress / non-normal / already-target activities.
  - Batch enable / disable: all-or-nothing, does NOT affect project
    `enabled` state, preserves cache invalidation.
  - Preview is read-only and treats disabled rules / unavailable projects
    as informational zero-count contributions (no `rule_disabled` /
    `project_not_available` / `too_many_matches` on the preview path).
- Service layer:
  - `worktrace/services/rule_batch_service.py` (new file): reuses
    `rule_impact_service` helpers (`_resolve_folder_rule`,
    `_resolve_keyword_rule`, `_project_available`, `_classify_activities`,
    `_sample_rows`) for a single matcher code path. Strict input
    normalization, transactional apply, all-or-nothing toggle.
  - `worktrace/services/project_inference_service.py` (modified):
    automatic-only skip guards + `is_archived = 0` filter on keyword rules.
  - `worktrace/services/folder_rule_service.py` (modified):
    `is_archived = 0` filter on folder rules.
  - `worktrace/services/rule_automation_service.py` (modified): facade
    delegates to `process_new_activity`.
- API layer (`worktrace/api/rule_api.py`, `worktrace/api/_write_contract.py`):
  - Four new facades: `preview_project_rules_batch_impact`,
    `backfill_project_rules_batch`, `set_project_rules_batch_enabled`,
    `automatic_rules_status`. Strict type validation on `rules` and
    `enabled`.
  - New stable error code `ERROR_TOO_MANY_RULES = "too_many_rules"` in
    `_write_contract.py`. Stable codes: `invalid_input` / `not_found` /
    `too_many_rules` / `rule_disabled` / `project_not_available` /
    `too_many_matches` / `operation_failed`.
  - Narrow display-safe payloads: counts + ≤ 20 sample rows for preview;
    update counts for apply; affected rule ids for toggle. No raw window
    title / file path / note / traceback / SQL leak.
- Bridge layer (`worktrace/webview_ui/bridge_rules.py`,
  `worktrace/webview_ui/bridge.py`):
  - Four new bridge methods: `preview_project_rules_batch_impact`,
    `backfill_project_rules_batch`, `set_project_rules_batch_enabled`,
    `automatic_rules_status`. They only call `worktrace.api.rule_api`;
    they never import services / db / collector / runtime / config.
  - Three new Chinese error-message maps
    (`_PROJECT_RULE_BATCH_PREVIEW_MESSAGES`,
    `_PROJECT_RULE_BATCH_APPLY_MESSAGES`,
    `_PROJECT_RULE_BATCH_TOGGLE_MESSAGES`); unknown codes collapse to a
    per-action Chinese message. `_validate_batch_rules` enforces the same
    shape at the bridge. `bridge.py` re-exports the three maps for
    backward compatibility.
  - No `.message` reads, no traceback / SQL / path / window_title /
    clipboard / note leak. All payloads JSON-serializable.
- Frontend (`worktrace/webview_ui/js/rules.js`,
  `worktrace/webview_ui/js/rules_rule_actions.js`,
  `worktrace/webview_ui/js/rules_render.js`,
  `worktrace/webview_ui/js/core.js`,
  `worktrace/webview_ui/index.html`,
  `worktrace/webview_ui/styles.css`):
  - Per-rule selection checkboxes + a batch action bar (preview / apply /
    enable / disable) rendered in `rules_render.js`; handlers in
    `rules_rule_actions.js`; batch containers in `index.html`; CSS in
    `styles.css`.
  - `_collectExistingRuleKeys` / `_pruneBatchSelection` in `rules.js`
    keep the selection stable across re-renders and drop keys for rules
    that no longer exist.
  - Batch apply uses `confirm` before calling the bridge; preview / apply
    / toggle refresh / reset the panel on success and preserve state on
    failure. New batch state variables in `rules_rule_actions.js` are
    isolated from existing keyword / folder / project / single-rule
    impact write states.
  - Comment wording in `core.js` / `rules_render.js` / `styles.css`
    avoids the literal `localStorage` / `sessionStorage` tokens so static
    contract scans stay green.
  - No `fetch` / `XMLHttpRequest` / `localStorage` / `sessionStorage`
    / ES module / external URL / new dependency / new JS file.
- Tests:
  - New `tests/test_project_rules_automatic_rules.py` (27 tests):
    priority ordering, folder-before-keyword, first-match-wins, skip
    guards (manual / hidden / deleted / in-progress / non-normal /
    already-target / disabled rule / archived project / excluded
    project), confidence + source + is_manual writes, no manual_override
    writes, archived-project no-match.
  - New `tests/test_project_rules_batch_operations.py` (46 tests): input
    validation, cross-path resolution, preview (success / read-only /
    display-safe / JSON-serializable / dedupe / disabled-rule zero
    counts), apply (success / display-safe / JSON-serializable / total
    cap 100 / `too_many_matches` writes nothing / collision
    first-rule-wins / dedupe stable order), skips, preflight rejections
    (disabled rule / unavailable project / not_found / invalid_input /
    too_many_rules), toggle (success / all-or-nothing / non-bool /
    too_many_rules / display-safe / JSON-serializable / cross-path), no
    schema change.
  - Extended bridge tests in `tests/test_webview_project_rules_bridge.py`
    (+29 tests, 416 total): all 4 new bridge methods covered for narrow
    payload, invalid-input short-circuit, stable error map, unknown-code
    collapse, exception collapse, no-sensitive-token leak,
    JSON-serializable; plus cross-call verification and 5I message-map
    re-export.
  - Extended static contract tests in
    `tests/webview/test_project_rules_static_contract.py` (+11 tests,
    364 total): batch DOM ids exist + hidden by default, static button
    count unchanged, `core.js` batch state variables, batch bridge calls
    exist, batch handlers no forbidden tokens, batch apply confirm text,
    state isolation, CSS classes + hidden rules, script order preserved.
- Affected runner mapping (`scripts/run_affected_tests.py`):
  - New C8 section for `rule_automation_service.py` → automatic rules
    tests + bridge + boundary.
  - New C9 section for `rule_batch_service.py` → batch operations tests
    + bridge + boundary.
  - `tests/test_run_affected_tests.py` extended with C8 / C9 coverage
    (triggers select the right targets, do not leak into CRUD / lifecycle
    / impact / static tests).
- Documentation: `README.md`, `docs/current-state.md`,
  `docs/ui-webview-migration.md`, and this file now describe the current
  phase as 5I and explicitly note that 5I ships automatic rules +
  selected-rule batch preview / apply / enable / disable foundation, not
  raw conflict preview or raw batch folder-rule backfill.

Phase 5I does not modify `WorkTrace.spec` resource list,
`worktrace/db.py`, `worktrace/schema.sql`, or any collector / privacy /
encrypted backup / statistics / export / timeline code. No DB schema
change. No new dependency. No new JS file. The WebView packaging static
test (`tests/test_webview_packaging.py`) and the `worktrace.webview_main`
import check were run and pass; the full PyInstaller build was not re-run
because no packaging or runtime behavior changed.

## Phase 5I Not Implemented

Phase 5I does not implement and does not start:

- Raw folder-rule conflict preview in WebView (the raw
  `folder_rule_service.preview_folder_rule_conflicts` is still NOT
  exposed to WebView; 5I batch preview reuses the display-safe
  `rule_impact_service` helpers, not the raw conflict path);
- Raw / unbounded batch folder-rule backfill (5I batch apply is capped at
  100 total updates per call and is all-or-nothing);
- Automatic-rule enable / disable toggle in the UI (5I ships the
  automatic application path + an `automatic_rules_status` read; the
  on/off switch for automatic application is deferred);
- Hard delete project (deferred);
- Project restore (un-archive) in WebView (deferred);
- Settings / Privacy / Encrypted Backup WebView migration;
- Excel / PDF / timesheet export or auto-submit;
- Folder opening or auto-open of exported files;
- DB schema changes;
- Legacy Tkinter UI removal;
- Tkinter fallback path;
- React / Vue / Vite / Node dependency;
- Local HTTP / FastAPI server;
- CDN / external JS / CSS / font / Google Fonts usage;
- `localStorage` / `sessionStorage` usage;
- Network requests;
- Any change to the existing Timeline, Statistics / CSV export, Overview,
  collector, privacy, encrypted backup, or database semantics.

## Phase 5I.1 Implemented Scope

Phase 5I.1 is a **hardening-only follow-up** to Phase 5I. It adds no new
user-visible capability. It only:

- Adds regression / boundary tests locking the Phase 5I automatic-rules path
  (thin facade over `project_inference_service.process_new_activity`; guard
  ordering: in-progress skip before assign; `automatic_rules_status` payload
  carries no on/off toggle field);
- Adds regression / boundary tests locking the Phase 5I selected-rule batch
  operations (non-int rule-id variants; malformed items; archived project
  preview returns zero counts not error; batch apply never sets
  `manual_override`; batch toggle does not change project enabled state;
  `too_many_rules` writes nothing; cross-path apply writes nothing);
- Adds a boundary test locking the four Phase 5I bridge methods
  (`preview_project_rules_batch_impact` / `backfill_project_rules_batch` /
  `set_project_rules_batch_enabled` / `automatic_rules_status`) on the
  composed `WebViewBridge` class;
- Adds static-contract tests locking the batch checkbox rule-key grouping,
  the absence of an automatic-rules on/off toggle in the frontend, the
  batch toolbar in-flight disabled guard, and the absence of storage /
  network APIs in the Project Rules JS modules;
- Fixes one pre-existing 5I-era boundary bug: a comment in
  `worktrace/webview_ui/js/rules_render.js` referenced forbidden tokens
  (`window_title` / `file_path_hint` / `path_hint` / clipboard / SQL /
  traceback) that tripped the global frontend boundary tests. The comment
  was reworded to avoid the literal tokens; no runtime behavior changed.
- Fixes one pre-existing 5I regression: `close_activity` did not re-trigger
  `process_new_activity` after transitioning an activity from in-progress
  to closed, so activities created in-progress (the normal collector
  flow) never received automatic folder / keyword rule application.
  `close_activity` now calls `process_new_activity` after the end_time
  update so enabled rules apply to just-closed eligible activities.

## Phase 5I.1 Not Implemented

Phase 5I.1 does not implement and does not start:

- Raw folder-rule conflict preview in WebView;
- Raw / unbounded batch folder-rule backfill;
- Automatic-rule enable / disable toggle in the UI;
- Hard delete project;
- Project restore (un-archive) in WebView;
- Settings / Privacy / Encrypted Backup WebView migration;
- DB schema changes (no new table / column / migration);
- New dependencies (no React / Vue / Vite / Node / local HTTP server);
- New JS file (the Project Rules surface still uses the existing classic
  split modules: `rules.js`, `rules_render.js`, `rules_rule_actions.js`,
  `rules_keyword_actions.js`, `rules_folder_actions.js`,
  `rules_project_actions.js`);
- Any change to collector / Timeline / Statistics / Export / privacy /
  encrypted backup runtime semantics.

## Phase 6A Implemented Scope

Phase 6A migrates the `page-settings` placeholder to a real read-only
**Settings / Privacy** status page. It only surfaces safety-status
information; it opens no write action.

Backend:

- New read-only facade `worktrace.api.settings_api.get_settings_privacy_status()`
  returning a fixed-shape payload:
  - `page = "settings_privacy"`, `phase = "6A"`,
    `storage_model = "local_only"`;
  - `clipboard_capture_enabled` (bool, sourced from existing
    `is_clipboard_capture_enabled()`);
  - `export_path_configured` (bool, sourced from existing `get_export_path()`
    truthiness — never the path text);
  - `secure_import_in_progress` (bool, sourced from
    `backup_api.is_secure_import_in_progress()`);
  - `encrypted_backup = {supported: true, export_available_in_webview: false,
    import_available_in_webview: false, manifest_preview_available_in_webview:
    false}`;
  - `destructive_actions = {clear_all_local_data_available_in_webview: false}`;
  - All fields JSON-serializable; exceptions collapse to
    `{"ok": false, "error": "加载设置状态失败"}` with no traceback / path /
    SQL / raw exception text.
- New bridge method `WebViewBridge.get_settings_privacy_status()` delegates
  to the facade with the standard error-collapse pattern. No new
  `bridge_settings.py` mixin is introduced; the single read-only method
  lives on the composed `WebViewBridge` class in `bridge.py`.
- `bridge.py` continues to import only `worktrace.api`; no
  `services / db / collector / security / runtime / config` imports.

Frontend:

- `index.html` replaces the `page-settings` placeholder with a real page
  shell. Stable DOM ids required for tests / future phases:
  `settings-refresh-btn`, `settings-error`, `settings-loading`,
  `settings-status`, `settings-storage-card`, `settings-privacy-card`,
  `settings-backup-card`, `settings-danger-card`.
- New classic IIFE module `worktrace/webview_ui/js/settings.js` defines
  `App.loadSettingsPrivacyStatus` (+ render / error / loading helpers).
  Only calls `App.callBridge("get_settings_privacy_status")`; catch blocks
  never read `.message`; dynamic rendering uses `textContent` only (no
  `innerHTML`); no write-side bridge methods are wired.
- `core.js` adds Phase 6A state vars (`settingsLoaded`, `settingsLoading`,
  `settingsRequestToken`).
- `init.js` lazy-loads settings status on first switch to the settings page
  and wires the refresh button; repeated page entries do not re-bind.
- `styles.css` adds `.settings-*` scoped classes (header, refresh button,
  loading / error / status grid, four cards including a red-bordered
  danger card).

Packaging:

- `WorkTrace.spec` bundles `worktrace/webview_ui/js/settings.js` in the
  `datas` list, between `statistics.js` and `rules.js`.
- `tests/webview/static_helpers.py` `ALL_JS_FILES` adds `settings.js` in
  the same position so the single source of truth for JS load order
  matches `index.html` and `WorkTrace.spec`.

Affected-test runner:

- New `scripts/run_affected_tests.py` section **K1. Settings / Privacy
  WebView** maps source-file triggers
  (`worktrace/api/settings_api.py`, `worktrace/api/backup_api.py`,
  `worktrace/webview_ui/bridge.py`, `worktrace/webview_ui/index.html`,
  `worktrace/webview_ui/js/settings.js`, `worktrace/webview_ui/js/init.js`,
  `worktrace/webview_ui/styles.css`, `WorkTrace.spec`,
  `tests/webview/static_helpers.py`) to a finite test target set
  (`tests/test_settings_privacy_status.py`,
  `tests/webview/test_settings_static_contract.py`,
  `tests/test_ui_backend_boundary.py`,
  `tests/webview/test_frontend_global_boundaries.py`,
  `tests/test_webview_packaging.py`,
  `tests/test_run_affected_tests.py`) plus the import smoke command. K1
  is independent of the Project Rules C series and must not trigger the
  Project Rules suite.

Tests:

- New `tests/test_settings_privacy_status.py` (API + bridge): success
  payload, `clipboard_capture_enabled` true/false, `export_path_configured`
  is bool and never leaks path text, `secure_import_in_progress` bool +
  backup-guard reflection, all three WebView availability flags false,
  `clear_all_local_data_available_in_webview` false, JSON-serializable,
  no sensitive-token leak, bridge narrow success payload, bridge exception
  collapse to `"加载设置状态失败"`, bridge method on the composed
  `WebViewBridge`, no write actions called during the status read, no
  schema change.
- New `tests/webview/test_settings_static_contract.py` (frontend
  contract): `page-settings` no longer contains the placeholder string,
  sidebar settings nav entry retained, required DOM ids present,
  `settings.js` loaded by `index.html`, `ALL_JS_FILES` includes
  `settings.js` with the same order as `index.html`, `WorkTrace.spec`
  bundles `settings.js`, JS only calls `get_settings_privacy_status`,
  no `export_encrypted_backup / import_encrypted_backup /
  parse_encrypted_backup_manifest / clear_all_local_data /
  set_setting_value / set_clipboard_capture_enabled` bridge calls, no
  fetch / XMLHttpRequest / WebSocket / EventSource / localStorage /
  sessionStorage / `document.cookie`, catch blocks do not read `.message`,
  dynamic rendering uses `textContent`, no clickable export / import /
  clear / save / clipboard-toggle write buttons.
- Updated placeholder-lock tests:
  `tests/webview/test_statistics_static_contract.py`,
  `tests/webview/test_timeline_static_contract.py`,
  `tests/webview/test_frontend_global_boundaries.py` — the
  `"WebView 迁移中"` placeholder lock is inverted because all sidebar
  pages are now migrated.
- Updated `tests/test_run_affected_tests.py` with K1 coverage (5 new
  tests).

## Phase 6A Not Implemented

Phase 6A does not implement and does not start:

- Save settings (no setting write API / bridge / UI);
- Clipboard capture toggle write (no `set_clipboard_capture_enabled`
  bridge / UI wiring);
- First-run notice view / accept in WebView;
- Native file / folder dialog;
- Encrypted backup export (`export_encrypted_backup`);
- Encrypted backup import (`import_encrypted_backup`);
- Encrypted backup manifest preview (`parse_encrypted_backup_manifest`);
- Clear-all-local-data (`clear_all_local_data`);
- Any database delete / rebuild / import / export write;
- Schema.sql modification (no new table / column / migration);
- New dependencies (no React / Vue / Vite / Node / local HTTP server /
  CDN / external font);
- `fetch` / `XMLHttpRequest` / `WebSocket` / `EventSource`;
- `localStorage` / `sessionStorage` / `document.cookie`;
- Legacy Tkinter fallback;
- Any change to collector / Timeline / Statistics / Export / privacy /
  encrypted backup runtime semantics;
- Any change to `bridge.py` import boundary (still only `worktrace.api`).

## Phase 6B Implemented Scope

Phase 6B opens the first minimal write capability on the Settings / Privacy
page: the **clipboard capture toggle**. The toggle writes
`clipboard_capture_enabled` through a narrow WebView bridge facade. Phase 6B
does not read or display clipboard content; the toggle only controls whether
local clipboard recording is enabled.

This phase also merges the originally planned 6A.1 hardening pass; no
separate 6A.1 phase is shipped.

Backend:

- New narrow write facade
  `worktrace.api.settings_api.set_clipboard_capture_enabled_for_webview(enabled: bool) -> dict[str, Any]`:
  - Only accepts `enabled is True` or `enabled is False`; any other
    type (`None`, `"true"` / `"false"` strings, `"1"` / `"0"`, `1` / `0`
    ints, `[]`, `{}`, `()`, `set()`, `object()`) is rejected with
    `{"ok": False, "error": "请选择有效的剪贴板记录状态"}` and does NOT
    mutate the underlying setting;
  - On success calls the existing `set_clipboard_capture_enabled(enabled)`
    and returns `{"ok": True, "status": <get_settings_privacy_status()["status"]>}`;
  - On any exception returns `{"ok": False, "error": "设置剪贴板记录失败"}`
    with no traceback / SQL / raw exception text;
  - Does not return the setting key raw value, clipboard content, export
    path, passphrase, or any sensitive metadata;
  - Does not call backup export / import / manifest, `clear_all_local_data`,
    or any schema mutation;
  - Added to `settings_api.__all__`.
- New bridge method `WebViewBridge.set_clipboard_capture_enabled(self, enabled) -> dict[str, Any]`:
  - Bridge-level strict `bool` guard mirrors the API facade (non-bool
    rejected with the same stable Chinese message before reaching the
    backend);
  - Delegates to `settings_api.set_clipboard_capture_enabled_for_webview(enabled)`;
  - On API `ok=True` returns `{"ok": True, "status": <status>}`;
  - On API `ok=False` passes the stable Chinese error through unchanged;
  - On any exception logs via `logger.exception(...)` and returns
    `{"ok": False, "error": "设置剪贴板记录失败"}`;
  - Payload never carries traceback, SQL, raw exception, path, clipboard
    content, or passphrase;
  - Defined directly on `WebViewBridge` in `bridge.py` (no new
    `bridge_settings.py` mixin); `bridge.py` continues to import only
    `worktrace.api`.

Frontend:

- `index.html` adds a clipboard toggle row inside the privacy card with
  stable DOM ids: `settings-clipboard-toggle`,
  `settings-clipboard-toggle-label`, `settings-clipboard-toggle-status`.
  The toggle is a checkbox (`<input type="checkbox">`), not a button.
  Page copy states clipboard recording is off by default, stored locally
  only, and the page does not display clipboard content.
- `core.js` adds `App.settingsWriteInProgress = false` (separate from
  `settingsLoading` so a write in flight does not pollute the read-state
  guard).
- `settings.js` header comment updated from Phase 6A read-only to Phase 6B
  clipboard toggle foundation; continues to note export / import / manifest
  / clear-all / save / file-dialog are not opened. New helper functions:
  - `setSettingsControlsDisabled(disabled)` — shared disable for the
    refresh button and the toggle (toggle also disabled until first
    successful load);
  - `setClipboardToggleStatus(text)` — updates the toggle status span via
    `textContent`;
  - `renderClipboardToggle(status)` — syncs `checked` / `disabled` / status
    text from the latest status snapshot;
  - `setClipboardCaptureEnabled(enabled)` — sets `settingsWriteInProgress`,
    disables controls, calls
    `App.callBridge("set_clipboard_capture_enabled", enabled)`, on success
    renders the returned status, on failure restores the previous checked
    state (`!enabled`) and shows a stable Chinese error, finally clears
    `settingsWriteInProgress` and re-enables controls based on `settingsLoading`;
  - `handleClipboardToggleChange(event)` — bound to the toggle `change`
    event; ignores events while disabled or while a write is in flight;
  - `renderSettingsStatus(status)` now calls `renderClipboardToggle(status)`;
  - `setSettingsLoading(loading)` now combines `loading || settingsWriteInProgress`
    when disabling controls;
  - catch blocks never read `.message`; dynamic rendering uses `textContent`
    only (no `innerHTML`); no network / storage / browser clipboard API.
- `init.js` binds the `settings-clipboard-toggle` `change` event to
  `App.handleClipboardToggleChange` inside `initButtons()`; no separate
  submit button is introduced.
- `styles.css` adds `.settings-toggle-row`, `.settings-toggle-label`,
  `.settings-toggle-control`, `.settings-toggle-status` scoped classes
  (plus `:disabled` variants). No effect on Project Rules / Timeline /
  Statistics pages; no external font; no CDN; no CSS framework.

Tests:

- `tests/test_settings_privacy_status.py` extended with Phase 6B API and
  bridge write tests: success true/false, payload only `ok` + `status`,
  JSON-serializable, no sensitive-token leak (path / clipboard content /
  passphrase / traceback / sqlite3 / raw exception), non-bool rejection
  (12 parametrized bad values), non-bool does not change the setting,
  setter exception returns generic error without leaking raw exception,
  no backup actions called, no `clear_all_local_data` called, no schema
  change; bridge method exists on composed `WebViewBridge`, signature has
  exactly one required `enabled` parameter (no optional / `*args`),
  bridge success true/false, bridge non-bool rejection + no setting change,
  bridge API exception collapse, bridge payload no sensitive-token leak,
  bridge no backup / no clear-all, bridge passes `ok=False` error through.
- `tests/webview/test_settings_static_contract.py` updated:
  - `test_settings_js_only_calls_allowed_bridge_method_6a` renamed to
    `test_settings_js_only_calls_allowed_bridge_methods_6b` with the new
    allowed list (`get_settings_privacy_status` +
    `set_clipboard_capture_enabled`); the old 6A forbidden assertion for
    `set_clipboard_capture_enabled` is removed so the new feature is not
    killed by the old test;
  - `test_index_html_settings_required_dom_ids_6a` extended with the three
    new toggle DOM ids;
  - `test_settings_js_does_not_use_network_or_storage_apis_6a` extended
    with `navigator.clipboard`;
  - `test_index_html_no_settings_write_buttons_6a` extended with
    `settings-path-btn`, `settings-file-dialog-btn`,
    `settings-manifest-btn`;
  - New 6B contract tests: `settingsWriteInProgress` declared in `core.js`,
    toggle write helper functions defined + exposed on `App`, toggle
    change handler bound in `initButtons`, controls disabled during load
    and write, toggle write failure restores previous checked state,
    `renderSettingsStatus` calls `renderClipboardToggle`, `.settings-toggle-*`
    CSS classes present.
- `tests/test_ui_backend_boundary.py` extended with two Phase 6B tests:
  bridge exposes `set_clipboard_capture_enabled` with exactly one required
  `enabled` parameter (no optional / `*args`), and the method body's
  executable code (docstring skipped) carries no forbidden runtime tokens
  (`traceback` / `str(exc)` / `repr(` / `format_exc` / `exc_info` /
  `.message` / `passphrase` / `clipboard_content` / `raw_exception`).
- `tests/test_run_affected_tests.py` K1 section docstrings updated to
  mention Phase 6A / 6B; K1 mapping itself is unchanged (it already covers
  all 6B-modified source files and test files); no new K2 section.

Affected-test runner:

- K1. Settings / Privacy WebView continues to cover
  `worktrace/api/settings_api.py`, `worktrace/api/backup_api.py`,
  `worktrace/webview_ui/bridge.py`, `worktrace/webview_ui/index.html`,
  `worktrace/webview_ui/js/settings.js`, `worktrace/webview_ui/js/init.js`,
  `worktrace/webview_ui/styles.css`, `WorkTrace.spec`,
  `tests/webview/static_helpers.py` →
  `tests/test_settings_privacy_status.py`,
  `tests/webview/test_settings_static_contract.py`,
  `tests/test_ui_backend_boundary.py`,
  `tests/webview/test_frontend_global_boundaries.py`,
  `tests/test_webview_packaging.py`,
  `tests/test_run_affected_tests.py` + import smoke. No K2 added.

## Phase 6B Not Implemented

Phase 6B does not implement and does not open UI / bridge entry for:

- Save settings (general setting write);
- `set_setting_value` WebView write entry;
- Export path setting;
- Native file / folder dialog;
- Encrypted backup export (`export_encrypted_backup`);
- Encrypted backup import (`import_encrypted_backup`);
- Encrypted backup manifest preview (`parse_encrypted_backup_manifest`);
- Clear-all-local-data (`clear_all_local_data`);
- First-run notice view / accept in WebView;
- Clipboard content reading, display, or return (the toggle only controls
  whether local clipboard recording is enabled; it never reads or shows
  copied text);
- Any database delete / rebuild / import / export write;
- Schema.sql modification (no new table / column / migration);
- New dependencies (no React / Vue / Vite / Node / local HTTP server /
  CDN / external font);
- `fetch` / `XMLHttpRequest` / `WebSocket` / `EventSource`;
- `localStorage` / `sessionStorage` / `document.cookie`;
- Browser Clipboard API (`navigator.clipboard`);
- Legacy Tkinter fallback;
- Any change to collector / Timeline / Statistics / Export / privacy /
  encrypted backup runtime semantics;
- Any change to `bridge.py` import boundary (still only `worktrace.api`).

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

## Phase DG1 Documentation Governance

Phase DG1 is a **docs/tests-only** documentation governance pass. It does
not modify any runtime code, the database schema, the WebView frontend
behavior, packaging, or dependencies. Its goal is to establish a "single
source of truth" documentation model so each future phase does not require
editing the same facts in multiple places.

Implemented Scope:

- **Established `docs/current-state.md` as the single current behavior
  source.** It was slimmed back to a one-screen snapshot (≤ 170 lines hard
  max). Per-phase Project Rules chronology was removed; only the current
  capability matrix remains.
- **Slimmed `README.md`.** The top Current state block is now a short
  pointer to `docs/current-state.md` and `docs/history/webview-phases.md`.
  The Core Capabilities Project Rules bullet no longer carries Phase 5B /
  5B.1 / 5C / 5C.1 / 5D / 5D.1 / 5E / 5E.1 / 5F / 5G chronology; it lists
  current capabilities and unsupported boundaries only.
- **Restored `docs/ui-webview-migration.md` to an architecture-only
  document.** The Status section is now a short pointer to current-state
  and history. The Migration Order is a high-level list; per-phase scope is
  deferred to this history file. The architecture decisions (destructive
  migration, why pywebview, no React / Vite / Vue, no local HTTP server,
  bridge boundary, security boundary, dependency handling, entry points,
  legacy Tkinter handling, WebView2 runtime handling) are preserved.
- **Consolidated release validation.** `docs/release-validation.md` is the
  canonical release baseline. `docs/release-checklist.md` was downgraded to
  a compatibility-pointer stub (retained, not hard-deleted) so existing
  references and test paths keep resolving.
- **Fixed the CSV / Excel export boundary.** The positive Excel export
  acceptance items in `docs/release-validation.md` (section "### J. Excel
  Export", "Summary sheet exists", "Activity Logs sheet exists", "Exported
  file opens in Excel", and the "Excel export is unusable" release blocker)
  were replaced with CSV-only export acceptance items reflecting the actual
  product boundary (CSV with UTF-8 BOM, Chinese headers, formula-injection
  escaping, display-safe content; Excel / PDF / timesheet export remain
  unsupported).
- **Downgraded research docs from default context.**
  `docs/v0.2-field-encryption-scan.md` was moved to
  `docs/research/v0.2-field-encryption-scan.md`. Research docs are not
  default reading context.
- **Updated `docs/ai-context-guide.md`** with a Documentation Governance
  section, a Research Docs section, and a corrected phase-range description
  (Phase 0A → current WebView phase instead of the stale Phase 0A → 4B).
- **Updated `tests/test_release_docs.py`** to lock the new governance
  rules: release-checklist stub assertions, release-validation canonical
  baseline assertions, CSV-only export assertions, README doc-diet
  assertions, current-state one-screen assertions, ui-webview-migration
  slimness assertions, and AI context governance assertions.

Not Implemented (unchanged boundaries):

- No runtime code, schema, WebView frontend, packaging, or dependency
  changes.
- No PyInstaller or installer build was run; this is docs/tests-only.
- No historical information was deleted; phase details moved out of README /
  current-state / ui-webview-migration are already present verbatim in this
  history file or were added as the Phase DG1 record above.

## Phase DG1.1 Documentation Residual Consistency Fix

Phase DG1.1 is a **docs/tests-only** follow-up to Phase DG1. It fixes the
residual contradictions that remained after the DG1 documentation governance
pass. It does not modify any runtime code, the database schema, the WebView
frontend behavior, packaging, or dependencies.

Implemented Scope:

- **Removed README Current Limitations contradiction.** The README top
  Current state block lists Project Rules user project create / edit /
  enable-disable / archive as supported, but the README Current Limitations
  section still listed "Project enable/disable" and "Project create/edit /
  delete/archive" as unsupported. The Current Limitations bullet now only
  lists the genuinely unsupported Project Rules capabilities (hard delete
  project, folder rule conflict preview, backfill, automatic rules, and
  batch Project Rules operations).
- **Tightened `docs/current-state.md` wording.** The Phase 5G description
  changed from the ambiguous "user project create / edit / enable-disable /
  archive on existing user projects" to the more precise "user project
  create, plus existing user project edit / enable-disable / archive", so
  the lifecycle scope is unambiguous.
- **Added regression tests in `tests/test_release_docs.py`.** New tests
  assert that the README Current Limitations section does not list Project
  Rules capabilities supported by the current-state matrix (project
  enable / disable, project create / edit / archive) as unsupported, that
  README still points at `docs/current-state.md`,
  `docs/history/webview-phases.md`, and `docs/ai-context-guide.md`, and that
  `docs/current-state.md` stays within the one-screen hard max.

Not Implemented (unchanged boundaries):

- No runtime code, schema, WebView frontend, packaging, or dependency
  changes.
- No PyInstaller or installer build was run; this is docs/tests-only.
- No new product capability was added or removed; only documentation /
  comment / test contradictions were fixed.
