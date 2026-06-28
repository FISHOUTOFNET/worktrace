# WorkTrace Current State

> **Default entry point for AI tools and developers.** Read this file first.
> It is a one-screen snapshot of what WorkTrace ships today. For architecture
> decisions see [`ui-webview-migration.md`](ui-webview-migration.md); for the
> full per-phase history see
> [`history/webview-phases.md`](history/webview-phases.md).

## Current Phase

**Phase 5G — Project lifecycle foundation + in-phase hardening.** Project
Rules now supports user project create / edit / enable-disable / archive on
existing user projects, in addition to the earlier folder / keyword rule
enable-disable, keyword create / edit / delete, and folder rule create /
edit / delete capabilities. Hard delete project, conflict preview, backfill,
automatic rules, and batch Project Rules operations remain unsupported. The
phase-by-phase chronology (5B / 5B.1 / ... / 5G) is archived in
[`history/webview-phases.md`](history/webview-phases.md).

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
- **Project Rules** (Phase 5A – 5G): project-grouped rule list showing
  project name / description, project enabled state, special `排除规则`
  marker, rule counts, folder rules, keyword rules, rule enabled state, and
  folder recursion scope. Current write capabilities are listed in the
  Project Rules matrix below. Per-phase scope details are archived in
  [`history/webview-phases.md`](history/webview-phases.md).

## Unmigrated Pages (Legacy Tkinter, Reference-Only)

- **Settings / Privacy / Encrypted Backup** — Phase 6, not started.

## Supported Timeline Write Operations

- Project reclassification of a session.
- Session-note editing.
- Single-activity `start_time` / `end_time` correction, incl. session-level.
- Single-activity split into two closed activities.
- Two-activity merge of adjacent, same-project / same-resource / same-status /
  same-source activities.
- Single-activity hide and soft delete.
- Batch project reassignment of multiple closed activities.
- Batch note overwrite on multiple closed activities.
- Single-activity restore (un-hide + un-soft-delete).
- Correction shell: a read-only context + navigation workspace reusing the
  above single/batch capabilities.
- Unified, stabilized Timeline status / error semantics.

## Project Rules Capability Matrix

- Read project-grouped folder / keyword rule list.
- Enable / disable existing folder / keyword rules.
- Keyword rule create / edit / delete.
- Folder rule create / edit / delete.
- User project create / edit / enable-disable / archive.
- Special `排除规则` boundary enforced (system / special projects rejected
  for lifecycle writes; enabling `排除规则` is never allowed).

## Statistics / Export Capability

- Read-only statistics summary (closed, non-hidden, non-deleted activities)
  with date-range validation (≤ 31 days).
- **CSV export write**: native save dialog, display-safe CSV (UTF-8 BOM,
  Chinese headers, formula-injection escaping). Returns basename only; never
  the full path, window title, file path, note, or clipboard.
- Excel / PDF / timesheet-template export, folder opening, auto-open, and
  auto-submit are explicitly unsupported.

## Explicitly Unsupported Capabilities

- Excel / PDF / timesheet-template export; folder opening; auto-open of the
  exported file; auto-submit of a timesheet.
- Hard delete project; folder-rule conflict preview; folder-rule backfill;
  automatic rules; batch Project Rules operations.
- Settings / Privacy / Encrypted Backup WebView migration.
- Batch hide / batch delete / batch restore; permanent delete; undo stack.
- Batch time / batch split / batch merge; note append / merge; auto-rule
  creation; global overlap detection.
- AI, server, payment, license, token, subscription, login, cloud sync, OCR,
  screenshots, screen recording, keyboard logging, automatic startup.
- Any DB schema change during development; `schema.sql` is the single source
  of truth. No Project Rules phase changed the schema.

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
`worktrace/webview_ui/js/` — `core.js`, `overview.js`, `timeline.js`,
`timeline_correction.js`, `statistics.js`, `rules.js`, `init.js` —
loaded in that order via plain `<script src="js/...">` tags. No ES
modules, no bundler, no Node/build step, no browser storage, and no network
requests.

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
# Affected tests (default for day-to-day iteration). Pure stdlib; maps
# changed source / docs / packaging paths to a finite pytest target set
# and never silently runs the full suite.
python scripts/run_affected_tests.py

# Full suite — reserve for core cross-cutting changes, pre-push, or
# release validation. Also runs in GitHub Actions CI.
pytest
```

Local paths: DB at `%LOCALAPPDATA%\WorkTrace\data\worktrace.db`; logs at
`%LOCALAPPDATA%\WorkTrace\logs\worktrace.log`; default exports at
`Documents\WorkTrace Exports`.
