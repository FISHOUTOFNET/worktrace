# WorkTrace v0.1 Lite

WorkTrace is a lightweight Windows local work-trace and timesheet helper. It runs as a portable desktop app, records active-window metadata locally, helps classify time into projects, and exports draft timesheets.

## Core Features

- CustomTkinter desktop UI with Overview, Time Details, Statistics/Export, Project Rules, and Settings/Privacy pages.
- SQLite local storage at `%LOCALAPPDATA%\WorkTrace\data\worktrace.db`.
- Background collector thread using pywin32/psutil on Windows.
- Idle, paused, excluded, normal, and error activity states.
- First-run privacy notice before any collection starts.
- Project creation, manual project assignment, notes, and soft delete.
- File, folder, and keyword project rules, including the special local `排除规则`.
- Excel export and Markdown weekly draft export.
- Collector heartbeat and startup recovery for unclosed records.
- Single-instance collector protection.

## Privacy And Permissions

无需注册。  
无需联网。  
无需管理员权限。  
不截屏。  
不录屏。  
不记录键盘。  
不读取正文。  
不上传数据。  
命中排除规则的窗口只保存匿名时间块。  
自动记录需由用户整理归类后再作为正式工时依据。

WorkTrace records only the current application name, process name, window title, identifiable local file path, start time, end time, duration, status, project, and note. It does not read Word/PDF/webpage/email/chat body content, browser history, cookies, passwords, clipboard data, camera, or microphone data.

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

## Local Paths

- Database: `%LOCALAPPDATA%\WorkTrace\data\worktrace.db`
- Logs: `%LOCALAPPDATA%\WorkTrace\logs\worktrace.log`
- Default exports: `Documents\WorkTrace Exports`

The app writes to user-local folders and does not require administrator privileges.

## Performance And Memory

WorkTrace keeps the startup path small by creating only the Overview page at launch. Time Details, Statistics/Export, Project Rules, and Settings/Privacy are created on first use and then kept mounted for smooth switching.

Heavy optional dependencies are loaded only when needed: `openpyxl` is imported during Excel export, and Windows process inspection dependencies are imported only when the real Windows adapter reads the foreground window. Shared duration formatting lives in `worktrace.formatters` so UI modules do not load export modules just to format `hh:mm:ss` values.

The default full-page data refresh interval is 10 seconds. A lightweight 1-second tick updates the current-activity label plus visible Overview, Time Details, and Statistics durations, so active records grow smoothly between full refreshes. Time Details uses value-only Treeview updates on that tick when the table structure is unchanged, and falls back to one full refresh only when sessions, resources, or details are added, removed, or reordered. Heavy refreshes are suspended during window resize/minimize/restore. Resize uses a content-area cover and can catch up before revealing; restore keeps the content tree mounted under a full-window cover, reveals the complete UI first, then merges delayed refresh work after the window is stable. On Windows, an optional native minimize hook pre-paints the restore cover and silently falls back to Tk events if unavailable.

## Project Classification

Folder project rules require a recognizable full local file path. File rules bind one specific file to a project. The special `排除规则` project supports file, folder, and keyword rules; matches are recorded anonymously as `已排除窗口` rather than classified as ordinary project time. Disabled projects remain visible but no longer participate in automatic classification.

If a file path is known but no rule or file default matches, Time Details may show the parent folder name as a suggested project. Suggested names are display-only hints and are not inserted into the `project` table.

Context carry-over applies to all normal non-anchor auxiliary activity between nearby matching anchor files. Browsers, chat apps, meeting apps, editors, IDEs, and other apps use the same project carry-over rules.

For reporting, a short interruption is also folded into the surrounding anchor project: if two anchors for project A enclose a contiguous block under 5 minutes containing only another normal project or idle time, the Time Details session and project statistics count that block under A. The original activity status and project assignment are preserved in the detailed records.

Report dates are project-aware across midnight. If a concrete project continues from the previous day into the next day, Overview, Time Details, Statistics, and exports keep counting that continuing project on the previous report date until the next concrete project appears. Idle time and uncategorized normal time switch at midnight and are split by calendar day.

Activity history is persisted after 30 seconds. All duration displays use exact `hh:mm:ss`, including exports and the live current-activity counter.

The Overview page shows `总时长`, `已归类`, and `未归类`. `已归类` is normal/mixed session time already assigned to a concrete project; clicking `未归类` opens Time Details filtered to uncategorized sessions, and clicking a recent session opens Time Details with that session selected.

## Collector Heartbeat

The collector writes `collector_status` and `last_collector_heartbeat` into the settings table. The UI displays:

- `记录中` when running
- `已暂停` when paused
- `采集器未运行` when stopped
- `状态异常` on collector errors

## Abnormal Recovery

If the app exits unexpectedly, startup recovery closes any `activity_log` rows where `end_time IS NULL`. It uses the last heartbeat when available; otherwise it closes at startup time and marks the row as `error` for review.

## Single Instance

WorkTrace prevents multiple collectors from writing to the same database. On Windows it uses a local mutex. A second UI instance may open, but it will not start another collector.

## Data Export And Clearing

The Project Rules page shows project binding summaries and manages file rules, folder rules, keyword rules, project edits, project enable/disable state, and the special `排除规则`. The top-right `新增项目` action opens project creation by default; each project card has its own `新增规则` action that opens rule creation preselected for that project.

The Settings page can clear all local data after this confirmation text:

```text
此操作将删除本机保存的所有工作轨迹、项目、规则和设置。删除后无法恢复。是否继续？
```

Clearing data recreates the database defaults, including the system projects `未归类` and `排除规则`.

## Tests

Run tests without requiring a real Windows foreground window:

```powershell
pytest
```

Tests use `worktrace.platforms.fake_adapter.FakeAdapter`.

## Uninstall

Close WorkTrace, then delete:

```text
%LOCALAPPDATA%\WorkTrace
Documents\WorkTrace Exports
```

Also remove the project folder or packaged executable if you no longer need it.

## Current Limitations

- Windows is the intended production platform; non-Windows runs use the fake adapter.
- No tray app, installer, service, driver, cloud sync, login, AI, OCR, screenshots, screen recording, or automatic startup.
- Date inputs are plain `YYYY-MM-DD` text fields in v0.1 Lite.
- Time Details uses plain text date fields in `YYYY-MM-DD` format.
