# WorkTrace v0.1 Lite

WorkTrace is a lightweight Windows local work-trace and timesheet helper. It runs as a portable desktop app, records active-window metadata locally, helps classify time into projects, and exports draft timesheets.

## Core Features

- CustomTkinter desktop UI with Timeline, Statistics/Export, and Settings/Privacy pages.
- SQLite local storage at `%LOCALAPPDATA%\WorkTrace\data\worktrace.db`.
- Background collector thread using pywin32/psutil on Windows.
- Idle, paused, excluded, normal, and error activity states.
- First-run privacy notice before any collection starts.
- Project creation, manual project assignment, notes, and soft delete.
- Simple keyword auto-classification rules.
- Excel export, Markdown weekly draft export, and export-all-local-data.
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
隐私排除窗口只保存匿名时间块。  
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

## Project Classification

Folder project rules require a recognizable full local file path. On Windows, WorkTrace tries Office/WPS COM first and then falls back to the foreground process open-file list, using only a unique exact file-name match.

If a file path is known but no rule or file default matches, the Timeline may show the parent folder name as a suggested project. Suggested names are display-only hints and are not inserted into the `project` table.

Context carry-over applies to all normal non-anchor auxiliary activity between nearby matching anchor files. Browsers, chat apps, meeting apps, editors, IDEs, and other apps use the same project carry-over rules.

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

The Settings page can export all local tables (`activity_log`, `activity_project_assignment`, `project`, `resource`, `folder_project_rule`, `project_rule`, `settings`) to Excel.

The Settings page can clear all local data after this confirmation text:

```text
此操作将删除本机保存的所有工作轨迹、项目、规则和设置。删除后无法恢复。是否继续？
```

Clearing data recreates the database defaults, including the default project `未归类`.

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
- The Timeline UI is intentionally simple for v0.1 Lite and uses plain text date fields in `YYYY-MM-DD` format.
