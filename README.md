# WorkTrace v0.1 Lite

WorkTrace is a lightweight Windows local work-trace and timesheet helper. It runs as a portable desktop app, records active-window metadata locally, helps classify time into projects, and exports draft timesheets.

## Core Features

- WebView desktop UI (pywebview + Microsoft Edge WebView2 Runtime) is the default and only shipping UI as of Phase 1. The Overview page is fully migrated (Phase 1); the Timeline / Time Details page is migrated as a read-only page (Phase 2) and hardened for real-run reliability, refresh stability, and privacy boundary enforcement (Phase 2.1); the Timeline page supports basic editing (Phase 3A): project reclassification and session-note editing. Phase 3A.1 hardens the basic editing path with stricter input validation, save-success baseline updates, note-length-overflow UI guards, and documentation cleanup. Phase 3B.1 adds the time-correction foundation (single-activity `start_time` / `end_time` editing with strict validation, `duration_seconds` recomputation, in-progress rejection, and single-activity session-level time correction). Phase 3B.1.1 hardens the time-correction path with a service-layer rowcount guard (race-condition defense), API-layer error mapping, and frontend saving-state fixes (session-time save button no longer stuck disabled; save flows fully decoupled). Phase 3B.2 adds the activity split foundation (single closed activity split at a user-supplied split point into two closed activities, with precise `duration_seconds` recomputation, project/resource inheritance, atomic transaction safety, and single-activity session-level split; multi-activity session whole-split is rejected). Phase 3B.2.1 hardens the split write path with a defensive `lastrowid` guard, clarified `created_at`/`updated_at` inheritance semantics, and explicit rollback tests for every transaction step (INSERT failure, assignment-copy failure, resource-copy failure). Phase 3B.3 adds the activity merge foundation (two closed, adjacent, same-project / same-resource / same-status / same-source activities merged into one; the earlier activity keeps its id and start_time, its end_time is extended to the later activity's end_time, and the later activity is soft-deleted; `duration_seconds` is precisely recomputed; notes are not concatenated; `project_session_note` is not migrated; only two activities per call; arbitrary-length batch merge and multi-activity session whole-merge are rejected; atomic transaction with rollback on any failure). Phase 3B.3.1 hardens the merge write path (confirms the transaction boundary covers both the kept-activity UPDATE and the later-activity soft-delete; confirms both UPDATEs raise on rowcount 0 and roll back; confirms a soft-delete UPDATE exception rolls back via the connection context manager so no partial write survives; adds explicit tests for excluded-vs-non-excluded rejection, no-partial-write for every rejection path, kept-fields-unchanged on validation failure, soft-delete exception rollback, and the full service-ValueError → API-error-code mapping table; restates that in-progress is determined by the raw DB `end_time IS NULL` column, not the projected display value; no new features, no new DB schema, no new UI controls). Deletion/hide, batch editing, auto-rule creation, complex correction pages, multi-activity session whole-split, arbitrary-length batch merge, and overlap detection are not yet available in the WebView UI. Statistics/Export, Project Rules, and Settings/Privacy remain on the legacy Tkinter / CustomTkinter code pending per-page migration.
- SQLite local storage at `%LOCALAPPDATA%\WorkTrace\data\worktrace.db`.
- Background collector thread using pywin32/psutil on Windows.
- Idle, paused, excluded, normal, and error activity states.
- First-run privacy notice before any collection starts.
- Project creation, manual project assignment, notes, and soft delete.
- File, folder, and keyword project rules, including the special local `排除规则`.
- Excel export from the legacy UI and all-local-data export from Settings.
- Collector heartbeat and startup recovery for unclosed records.
- Single-instance collector protection.

## v0.2 Boundary

The current implementation remains v0.1 Lite. The next-version boundary is documented in [`docs/v0.2-boundary.md`](docs/v0.2-boundary.md): all local features remain free and usable without registration, payment, or network access; paid features are limited to opt-in server-side AI classification and AI project-session note drafts; AI is off by default and must not affect local functionality.

Phase 1A local security design is documented in [`docs/v0.2-local-security-design.md`](docs/v0.2-local-security-design.md). It covers the independent crypto foundation, DPAPI keyring, and `.wtbackup` format without changing the existing runtime database behavior.

Phase 1B extends the v0.2 local security foundation with encrypted `.wtbackup` export/import. A `.wtbackup` file is a local encrypted file created on the user's request; WorkTrace never uploads it. The backup passphrase is chosen by the user at export time and is not recoverable if forgotten. See [`docs/v0.2-local-security-design.md`](docs/v0.2-local-security-design.md) for the full Phase 1B scope, payload format, and import semantics.

WebView Phase 1 is a destructive UI migration: the WebView UI is now the default and only shipping UI. `python -m worktrace.main` (and the packaged `WorkTrace.exe`) start the WebView UI directly. The legacy `--webview` flag is accepted as a no-op compatibility flag and does not change behavior. The legacy Tkinter / CustomTkinter UI under `worktrace/ui` is retained only as legacy code pending per-page migration and removal; it is not a supported runtime path and is not started by the default entry point.

WorkTrace requires the Microsoft Edge WebView2 Runtime on Windows. When the runtime is missing, WorkTrace prints a clear install prompt and exits with a non-zero code; it does not auto-download the runtime and does not fall back to Tkinter. Windows 11 ships with the Evergreen WebView2 Runtime preinstalled; some Windows 10 machines need a manual install from Microsoft.

See [`docs/ui-webview-migration.md`](docs/ui-webview-migration.md) for the Phase 1 scope, destructive-migration principles, packaging conclusions, and stop-loss conditions.

## Privacy And Permissions

无需注册。  
无需联网。  
无需管理员权限。  
不截屏。  
不录屏。  
不记录键盘。  
不主动读取正文。  
不上传数据。  
命中排除规则的窗口只保存匿名时间块。  
复制文字记录默认关闭；开启后仅本地保存复制到剪贴板的文本，并自动清理 30 天前的复制文字。  
自动记录需由用户整理归类后再作为正式工时依据。

WorkTrace records the current application name, process name, window title, identifiable local file path, local folder-rule file-name/path indexes, start time, end time, duration, status, project, and notes. If the user enables clipboard text recording in Settings, it also stores copied text locally for up to 30 days. It does not actively read Word/PDF/webpage/email/chat body content, browser history, cookies, passwords, camera, or microphone data.

## Portable Usage

Install dependencies in a Python 3.11+ environment:

```powershell
pip install -r requirements.txt
```

Start the app:

```powershell
python -m worktrace.main
```

The first launch shows the privacy notice. The collector starts only after the notice is accepted.

As of Phase 1, the default UI is WebView. Closing the WebView window exits WorkTrace cleanly (the collector thread, folder-index worker, and single-instance lock are released). The legacy Tkinter tray-icon behavior is not part of the default runtime path; it remains in the legacy `worktrace/ui` package pending removal.

## Windows Packaging

Packaging is optional and only needed when producing distributable Windows builds. It relies on extra build dependencies that are not part of the runtime requirements.

Install the runtime dependencies first, then add the build dependencies only when packaging:

```powershell
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

`requirements-dev.txt` extends `requirements.txt` with `pyinstaller`. The same build dependency set covers both the single-file executable and the per-user installer, because `scripts\build_windows_installer.ps1` also drives PyInstaller to wrap the installer payload.

Build the single-file executable:

```powershell
python -m PyInstaller --noconfirm --clean WorkTrace.spec
```

Build the per-user installer (run after the single-file executable has been built, since the installer wraps `dist\WorkTrace.exe` as its payload):

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\build_windows_installer.ps1
```

The build outputs are:

- `dist\WorkTrace.exe` — single-file application.
- `dist\WorkTrace-Setup.exe` — current-user installer.

The installer copies WorkTrace to `%LOCALAPPDATA%\Programs\WorkTrace` and creates a current-user Start Menu shortcut. It installs per-user only: it does not write to `Program Files` and does not request administrator privileges.

Build artifacts (`build/`, `dist/`, generated `.spec` files other than `WorkTrace.spec`) must not be committed to Git; `.gitignore` already excludes them. The release acceptance steps for both builds are documented in [`docs/release-checklist.md`](docs/release-checklist.md).

## Release Validation

Before a Windows release, use [`docs/release-validation.md`](docs/release-validation.md) as the v0.1 Lite release-candidate baseline. Run `pytest`, require GitHub Actions CI to pass, and validate both the PyInstaller exe and the per-user installer.

## Local Paths

- Database: `%LOCALAPPDATA%\WorkTrace\data\worktrace.db`
- Logs: `%LOCALAPPDATA%\WorkTrace\logs\worktrace.log`
- Optional COM path catalog: `%LOCALAPPDATA%\WorkTrace\com_path_catalog.json`
- Default exports: `Documents\WorkTrace Exports`

The app writes to user-local folders and does not require administrator privileges.

`schema.sql` is the single source of truth for the local database structure. The project is in pre-release development, so old databases are not guaranteed to be compatible. If the schema changes, delete the local database file or use the Settings page to clear and rebuild all data.

## Performance And Memory

WorkTrace keeps the startup path small by creating only the Overview page at launch. Time Details, Statistics/Export, Project Rules, and Settings/Privacy are created on first use and then kept mounted for smooth switching.

Heavy optional dependencies are loaded only when needed: `openpyxl` is imported during Excel export, and Windows process inspection dependencies are imported only when the real Windows adapter reads the foreground window. Shared duration formatting lives in `worktrace.formatters` so UI modules do not load export modules just to format `hh:mm:ss` values.

Displayed UI text supports copying through right-click copy menus. Time Details tables also support right-click copying for the current cell, row, or page text, while `Ctrl+C` keeps copying selected table rows before falling back to the current page summary.

The default full-page data refresh interval is 10 seconds. A lightweight 1-second tick updates the current-activity label plus visible Overview, Time Details, and Statistics durations, including the current activity before it is persisted to history, so active records grow smoothly between full refreshes. The current-activity label previews automatic project inference immediately: folder rules and keyword rules win before parent-folder suggestions, even while the activity is still under the 30-second history threshold. During that threshold window, only the Overview recent-project row and the Time Details project/session row temporarily continue the previous confirmed project counter; the current-activity label, KPIs, Statistics, and activity details keep using the real snapshot. Time Details uses value-only Treeview updates on that tick when the table structure is unchanged, and falls back to one full refresh only when sessions or details are added, removed, or reordered. Heavy refreshes are suspended during window resize/minimize/restore. Resize uses a content-area cover and can catch up before revealing; restore keeps the content tree mounted under a full-window cover, reveals the complete UI first, then merges delayed refresh work after the window is stable. On Windows, WorkTrace relies on Tk window events for minimize/restore handling and keeps native WndProc subclassing disabled for Python runtime stability.

Time Details no longer supports manual session splitting, merging same-name project segments, or moving an activity into another session. Project corrections operate on the selected project session or selected detail activity only. The detail table is the only activity-level view; file identity is derived from the activity's app, process, window title, and file path hint at runtime. Project-session notes live in the selected session summary area: an empty note shows the generated summary as light placeholder text, and user text is saved automatically without a separate save button.

## Project Classification

Each activity record first generates a `DetectedResource` from the active window's app name, process name, window title, and file path hint. The `resource_kind` is one of `local_file`, `office_document`, `email`, `browser_tab`, `ide_file`, `app`, `system`, or `unknown`. Folder rules, keyword rules, and the `排除规则` project match against safe metadata only: resource path, path hint, display name, uri_host, app name, process name, and window title. WorkTrace does not read file contents, email bodies, or browser history.

Folder project rules prefer a recognizable full local file path, and WorkTrace also keeps a local file-name/path index for bound folders so title-only file windows can still match the correct rule. Any full local file path can be an anchor regardless of extension, and the folder index also covers all file extensions, so rules can match source code, CAD drawings, design files, images, PDFs, and Office documents. Keyword rules match activity app names, process names, window titles, known local file paths, and copied text when clipboard recording is enabled. The special `排除规则` project supports folder and keyword rules, starts disabled with no default rules, and records matches anonymously as `已排除窗口` only after the user enables it. Disabled projects remain visible but no longer participate in automatic classification.

If a file path is known but no folder or keyword rule matches, Time Details may show the parent folder name as a suggested project only for the built-in low-risk document extensions. Suggested names are display-only hints and are not inserted into the `project` table. User-created folder and keyword rules are not limited by that extension list.

On Windows, the collector resolves active file paths in this order: full paths visible in the window title, a best-effort COM path catalog, a timeout-limited helper process that calls `psutil.Process(pid).open_files()` for the foreground process, then the local folder-rule index. The open-files helper runs as a subprocess to avoid blocking the UI: in development it uses `python -m worktrace.platforms.open_files_helper`, and in the PyInstaller packaged build it re-enters the executable with `WorkTrace.exe --open-files-helper`. The open-files and index fallbacks use the file name visible in the title and accept a path only when the result is unambiguous. If the helper times out, that PID is skipped briefly so a slow handle enumeration cannot freeze the UI.

Folder indexes are local derived caches. They store file names and paths under user-bound folder rules, do not read file contents, and only affect activities after the index `valid_from` time. If the same title file name appears under different active projects, WorkTrace treats it as ambiguous and leaves the activity unclassified.

The built-in COM catalog covers common Office/WPS apps, Acrobat, AutoCAD, Photoshop, Illustrator, InDesign, CorelDRAW, and SOLIDWORKS when their ProgIDs are registered locally. Advanced users may add entries in `%LOCALAPPDATA%\WorkTrace\com_path_catalog.json`; there is no UI for this file. Example:

```json
{
  "entries": [
    {
      "name": "Custom App",
      "process_names": ["custom.exe"],
      "prog_ids": ["Custom.Application"],
      "path_expressions": ["ActiveDocument.FullName"]
    }
  ]
}
```

Context carry-over applies to normal non-anchor auxiliary activity. A single previous or next concrete anchor can carry context within 15 minutes. Two matching concrete anchors carry a continuous auxiliary block regardless of that 15-minute window. When clipboard recording is enabled, copying text and switching to the next normal activity within 10 seconds is treated as a stronger same-project signal than anchor/time context, but it does not override manual assignments, folder rules, or keyword rules. Idle and paused records stop anchor search; excluded and error records do not. Per-date context recomputation is skipped when the activity, assignment, project, rule, clipboard, and context-setting fingerprint is unchanged, so switching pages does not repeatedly rescan and rewrite the same day.

For reporting, a short interruption is also folded into the surrounding anchor project: if two anchors for project A enclose a contiguous block under 5 minutes containing only another normal project or idle time, the Time Details session and project statistics count that block under A. The original activity status and project assignment are preserved in the detailed records.

Report dates are calendar-day based. Activities are split at local midnight for Overview, Time Details, Statistics, and exports. When the collector crosses midnight during an existing concrete project, the new post-midnight activity gets a persistent temporary `midnight_anchor` assignment to the previous concrete project, bypassing the 30-second history threshold for that new activity only. This does not change folder rules, keyword rules, or any long-term per-file binding.

Activity history is persisted after 30 seconds. All duration displays use exact `hh:mm:ss`, including exports and the live current-activity counter.

The Overview page shows `总时长`, `已归类`, and `未归类`. `已归类` is normal/mixed session time already assigned to a concrete project; clicking `未归类` opens Time Details filtered to uncategorized sessions, and clicking a recent session opens Time Details with that session selected.

## Collector Heartbeat

The collector writes `collector_status` and `last_collector_heartbeat` into the settings table. The UI displays:

- `记录中` when running
- `已暂停` when paused
- `采集器未运行` when stopped
- `状态异常` on collector errors

The tray icon mirrors the same state on the legacy Tkinter UI only: color means WorkTrace is recording, while the monochrome icon means recording is paused, stopped, or in an error state. The default WebView UI does not implement a tray icon in Phase 1; the status label in the Overview sidebar mirrors the same `记录中 / 已暂停 / 采集器未运行 / 状态异常` states.

## Abnormal Recovery

If the app exits unexpectedly, startup recovery closes any `activity_log` rows where `end_time IS NULL`. It uses the last heartbeat when available; otherwise it closes at startup time and marks the row as `error` for review. Recovered rows that cross midnight are split into calendar-day records.

## Single Instance

WorkTrace prevents multiple collectors from writing to the same database. On Windows it uses a local mutex. A second UI instance may open, but it will not start another collector.

## Data Export And Clearing

The Project Rules page shows project binding summaries and manages file rules, folder rules, keyword rules, project edits, project enable/disable state, and the special `排除规则`. The top-right `新增项目` action opens project creation by default; each project card has its own `新增规则` action that opens rule creation preselected for that project.

The Settings page saves the clipboard text recording toggle immediately when it is changed. It can also clear all local data after this confirmation text:

```text
此操作将删除本机保存的所有工作轨迹、项目、规则和设置。删除后无法恢复。是否继续？
```

Clearing data recreates the database defaults, including the system projects `未归类` and `排除规则`, with the `排除规则` project starting disabled and empty. The all-data export includes clipboard events and project session notes, and intentionally excludes folder index tables because they are derived caches that may contain many local file paths.

The Settings/Privacy page also offers encrypted `.wtbackup` export and import. A `.wtbackup` file is a local encrypted backup created on the user's request; WorkTrace never uploads it. The backup may include copied text if clipboard recording was enabled, so the UI warns before export. Import is replace-only (or import into an empty profile); a wrong passphrase, corrupted backup, or unsupported version never damages the current database. The backup passphrase is not recoverable if forgotten. Encrypted import pauses recording during replacement and keeps recording paused after a successful import.

## Tests

Run tests without requiring a real Windows foreground window:

```powershell
pytest
```

Tests use `worktrace.platforms.fake_adapter.FakeAdapter`.

## Uninstall

Exit WorkTrace from the WebView window close button (the default UI does not implement a tray icon in Phase 1), then delete:

```text
%LOCALAPPDATA%\WorkTrace
Documents\WorkTrace Exports
```

Also remove the project folder or packaged executable if you no longer need it.

## Current Limitations

- Windows is the intended production platform; non-Windows runs use the fake adapter.
- No service, driver, cloud sync, login, AI, OCR, screenshots, screen recording, or automatic startup.
- Date inputs are plain `YYYY-MM-DD` text fields in v0.1 Lite.
- Time Details uses plain text date fields in `YYYY-MM-DD` format.
