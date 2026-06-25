# WorkTrace WebView UI Migration

## Status

- Current phase: 3A (Overview fully migrated; Timeline read-only page
  migrated and hardened; Timeline basic editing — project reclassification
  and session-note editing — implemented; WebView is the default and only
  shipping UI).
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
  scope. **Current phase.**
- Phase 3B: Timeline advanced editing (time correction, split, merge,
  delete, batch editing, correction page) — not yet started.
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
