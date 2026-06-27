# WorkTrace Current State

> **Default entry point for AI tools and developers.** Read this file first.
> It is a one-screen snapshot of what WorkTrace ships today. For architecture
> decisions see [`ui-webview-migration.md`](ui-webview-migration.md); for the
> full per-phase history see [`history/webview-phases.md`](history/webview-phases.md).

## Current Phase

**Phase 5A — Project Rules WebView read-only foundation.** The Project Rules
page is now a WebView read-only page for viewing project-grouped folder /
keyword rules. Phase 5A does not add Project Rules write actions, conflict
preview, backfill, automatic rules, schema changes, new frontend
dependencies, or new export formats. All earlier WebView migration phases
(Phase 0A → Phase 4B.1) are completed. README, this file, and
`ui-webview-migration.md` all describe the current phase as 5A.

## Default UI

- WebView (`pywebview` + Microsoft Edge WebView2 Runtime) is the default and
  only shipping UI. Start with `python -m worktrace.main`.
- No Tkinter fallback. The legacy `worktrace/ui` package is kept in the tree
  as reference-only code pending per-page migration; it is not a supported
  runtime path.
- Missing WebView2 Runtime is a blocking error with a clear Chinese install
  prompt; WorkTrace never auto-downloads it.

## Migrated Pages

- **Overview** (Phase 1): KPIs (date / total / projects / classified /
  uncategorized), current activity, recent activities, error banner,
  pause/resume, auto-refresh.
- **Timeline / Time Details** (Phase 2 / 2.1 + 3A–3C.1): date navigation,
  daily total, session list, per-session activity details, read-only
  rendering hardened for real-run reliability, plus the editing /
  correction capabilities listed below.
- **Statistics / Export** (Phase 4A / 4A.1 / 4B / 4B.1): read-only summary
  cards, grouped tables (by project / by app / by status), export preview,
  CSV export write, and hardened save dialog / packaging / static contract.
- **Project Rules** (Phase 5A): read-only project-grouped rule list showing
  project name / description, project enabled state, special `排除规则`
  marker, rule counts, folder rules, keyword rules, rule enabled state, and
  folder recursion scope. Project/Rule creation, editing, deletion,
  enable/disable, conflict preview, backfill, and automatic rules are still
  not open in WebView.

## Unmigrated Pages (Legacy Tkinter, Reference-Only)

- **Settings / Privacy / Encrypted Backup** — Phase 6, not started.

## Supported Timeline Write Operations

- Project reclassification of a session (Phase 3A).
- Session-note editing (Phase 3A).
- Single-activity `start_time` / `end_time` correction, incl. session-level
  (Phase 3B.1).
- Single-activity split into two closed activities (Phase 3B.2).
- Two-activity merge of adjacent, same-project / same-resource / same-status /
  same-source activities (Phase 3B.3).
- Single-activity hide and soft delete (Phase 3B.4).
- Batch project reassignment of multiple closed activities (Phase 3B.6).
- Batch note overwrite on multiple closed activities (Phase 3B.7).
- Single-activity restore (un-hide + un-soft-delete) (Phase 3B.8).
- Correction shell: a read-only context + navigation workspace reusing the
  above single/batch capabilities (Phase 3B.5B / 3B.9).
- Unified, stabilized Timeline status / error semantics (Phase 3C / 3C.1).

## Statistics / Export Capability

- Read-only statistics summary (closed, non-hidden, non-deleted activities)
  with date-range validation (≤ 31 days).
- **CSV export write** (Phase 4B / 4B.1): native save dialog, display-safe CSV
  (UTF-8 BOM, Chinese headers, formula-injection escaping). Returns basename
  only; never the full path, window title, file path, note, or clipboard.
  Phase 4B.1 hardened the save dialog compatibility (all return shapes,
  missing constants, exceptions -> stable Chinese), verified the `.csv` suffix
  is preserved case-insensitively, and locked the frontend static contract
  (independent load/export state, no raw exception reads, no forbidden
  handlers).

## Explicitly Unsupported Capabilities

- Excel / PDF / timesheet-template export; folder opening; auto-open of the
  exported file; auto-submit of a timesheet.
- Project Rules creation / editing / deletion; Project or Rule
  enable/disable; folder-rule conflict preview; folder-rule backfill;
  automatic rules; batch Project Rules operations.
- Settings / Privacy / Encrypted Backup WebView migration.
- Batch hide / batch delete / batch restore; permanent delete; undo stack.
- Batch time / batch split / batch merge; note append / merge; auto-rule
  creation; global overlap detection.
- AI, server, payment, license, token, subscription, login, cloud sync, OCR,
  screenshots, screen recording, keyboard logging, automatic startup.
- Any DB schema change during development; `schema.sql` is the single source
  of truth.

## Architecture Boundary

```
WebView (index.html / js/*.js / styles.css)
   └─> Python bridge (worktrace.webview_ui.bridge)
         └─> worktrace.api  (the ONLY backend layer the bridge may import)
               └─> worktrace.services
                     └─> worktrace.db   (schema.sql is the single source of truth)
   (collector thread ──> worktrace.collector)
```

Frontend JS layout (Phase R2, no behavior change): the former single
`app.js` is split by feature into local classic scripts under
`worktrace/webview_ui/js/` — `core.js` (shared `window.WorkTraceApp`
namespace, state, bridge call, generic helpers), `overview.js`,
`timeline.js`, `timeline_correction.js`, `statistics.js`, `rules.js`,
`init.js` —
loaded in that order via plain `<script src="js/...">` tags. No ES
modules, no bundler, no Node/build step. Product behavior is unchanged.

- The bridge may import `worktrace.api` and nothing else from the backend.
- The bridge returns `{"ok": false, "error": "<chinese>"}` on failure; it
  never returns tracebacks, SQL, or sensitive raw fields.
- Enforced by `tests/test_ui_backend_boundary.py`.

## Privacy Boundary

- No registration, no network, no admin rights, no screenshots / recording /
  keyboard logging. Active window metadata only (app, process, window
  title, local file path hint, start/end time, duration, status, project,
  notes). No reading of document / email / webpage / browser-history bodies.
- Clipboard text recording is off by default; when enabled it stores copied
  text locally only and auto-clears entries older than 30 days.
- `.wtbackup` is a local encrypted file; WorkTrace never uploads it; the
  passphrase is not recoverable.

## Common Test Commands

```powershell
# Full suite (uses worktrace.platforms.fake_adapter.FakeAdapter)
pytest

# Only the split WebView static-contract tests
pytest tests/webview/

# Entry-point sanity (does not start a GUI on import)
python -c "import worktrace.webview_main; print('ok')"

# Build the single-file executable
python -m PyInstaller --noconfirm --clean WorkTrace.spec
```

Local paths: DB at `%LOCALAPPDATA%\WorkTrace\data\worktrace.db`; logs at
`%LOCALAPPDATA%\WorkTrace\logs\worktrace.log`; default exports at
`Documents\WorkTrace Exports`.
