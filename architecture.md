# WorkTrace v0.1 Lite Architecture

## 1. Project Summary

WorkTrace is a lightweight Windows local work-trace and timesheet helper.

It records only:

* active application name
* process name
* active window title
* start time
* end time
* duration
* record status
* user-selected project
* user note

It must not record:

* screenshots
* screen recordings
* keyboard input
* mouse click contents
* file contents
* webpage contents
* email contents
* chat contents
* clipboard contents
* browser history
* browser cookies
* browser passwords
* camera or microphone data
* cloud data

The v0.1 Lite goal is to implement this minimal local loop:

```text
Start portable Windows app
→ show first-run privacy notice
→ collect active window metadata
→ detect idle time
→ anonymize excluded/private windows
→ let user organize and classify records
→ summarize time by project
→ export Excel timesheet from the UI
```

This version must be local-only, offline-capable, account-free, and runnable without administrator privileges.

---

## 2. Implementation Guardrails

Implementation must follow this architecture and must not add features outside this document without explicit instruction.

Do not add:

* AI
* cloud sync
* login or account system
* tray app
* installer
* browser extension
* OCR
* screenshot capture
* screen recording
* keyboard hook
* mouse-click content logging
* file-content parsing
* webpage-content parsing
* email-content parsing
* hidden background service
* Windows service
* driver
* automatic startup on boot

Prefer simple, explicit, testable code over abstraction-heavy architecture.

The target is a reliable v0.1 Lite, not a complete commercial product.

---

## 3. Product Scope

### 3.1 In Scope

Implement:

1. Windows active-window collection.
2. App name, process name, window title collection.
3. Start time, end time, and duration tracking.
4. Idle detection.
5. Excluded/private window anonymization.
6. Local SQLite storage.
7. Project creation and selection.
8. Time Details view.
9. Record editing.
10. User notes.
11. Simple keyword-based auto-classification.
12. Project time statistics.
13. Date-range statistics.
14. Excel export.
15. Markdown weekly draft export service/API.
16. Pause / resume collection.
17. Collector heartbeat display.
18. Single-instance protection.
19. Recovery of unclosed records after abnormal shutdown.
20. Local data clearing.
21. Local data export.
22. First-run privacy notice.
23. Local logging.

### 3.2 Out of Scope

Do not implement:

1. AI.
2. cloud sync.
3. account system.
4. team management.
5. employee monitoring.
6. screenshot or screen recording.
7. keyboard logging.
8. mouse-click content logging.
9. reading Word / PDF / webpage / email body text.
10. browser extension.
11. mobile app.
12. Word export.
13. client / project / task three-level hierarchy.
14. complex rule priority system.
15. tray app.
16. auto-start on boot.
17. installer.
18. background Windows service.
19. driver.
20. admin privilege request.

---

## 4. Technology Stack

### 4.1 Required Stack

Use:

```text
Python 3.11+
SQLite
CustomTkinter
pywin32
psutil
openpyxl
PyInstaller
pytest
```

### 4.2 UI Choice

Use `CustomTkinter` for v0.1 Lite.

Do not use Streamlit as the final UI. Streamlit may be used only for throwaway demos, not for the architecture implemented from this document.

### 4.3 Windows API Isolation

The real collector uses Windows APIs through `pywin32`.

The codebase must isolate Windows-specific calls behind an adapter so tests can run without needing a real Windows foreground window.

Implement:

```text
worktrace/platforms/windows_adapter.py
worktrace/platforms/fake_adapter.py
```

`windows_adapter.py` is used in production on Windows.

`fake_adapter.py` is used in tests and non-Windows development environments.

---

## 5. Runtime Model

### 5.1 Process Model

v0.1 Lite must use a single-process, multi-thread architecture.

Runtime model:

```text
Main process
├── UI thread: CustomTkinter main loop
└── Collector thread: background collector loop
```

Do not implement the collector as:

* a separate Windows service
* a separate daemon process
* a hidden background process
* an auto-start program

The collector runs only while the WorkTrace app is running.

### 5.2 Thread Boundaries

The UI thread owns all UI widgets.

The collector thread must not directly update UI widgets.

UI must refresh by polling database and collector status using Tkinter `after()`.

Default UI refresh interval:

```text
10 seconds for full page data refresh
1 second for current-activity label and live duration refresh
```

Collector thread communicates state through:

1. SQLite records.
2. `settings` table heartbeat values.
3. in-memory stop event.
4. in-memory pause/resume state if needed.

### 5.3 Shutdown Rules

On app exit:

1. UI sets `collector_stop_event`.
2. Collector loop exits cleanly.
3. Collector closes current open activity record.
4. Collector writes `collector_status = stopped`.
5. Collector writes `last_shutdown_at = current local timestamp`.
6. Single-instance lock is released.
7. UI exits.

If graceful shutdown fails, recovery logic must handle unclosed records on next startup.

---

## 6. Startup Order

`main.py` must follow this startup order:

1. Resolve local paths.
2. Create required local directories.
3. Initialize logging.
4. Initialize database.
5. Apply SQLite PRAGMA configuration.
6. Seed default settings and default project.
7. Acquire single-instance lock.
8. Recover unclosed records.
9. Launch UI.
10. Show first-run privacy notice if not accepted.
11. Start collector thread only after first-run notice is accepted.
12. On exit, stop collector and close any open record.

Collection must not start before the first-run privacy notice is accepted.

---

## 7. Runtime Paths

Use user-local paths. Do not write to `Program Files`.

Default data directory:

```text
%LOCALAPPDATA%\WorkTrace
```

Default database path:

```text
%LOCALAPPDATA%\WorkTrace\data\worktrace.db
```

Default log path:

```text
%LOCALAPPDATA%\WorkTrace\logs\worktrace.log
```

Default export directory:

```text
Documents\WorkTrace Exports
```

Create directories if absent.

The app must run without administrator privileges.

---

## 8. Logging

Use Python `logging`.

Log file path:

```text
%LOCALAPPDATA%\WorkTrace\logs\worktrace.log
```

Log at least:

1. app startup
2. app shutdown
3. database initialization
4. collector start
5. collector stop
6. state transitions
7. recovery actions
8. export success
9. export errors
10. database write errors
11. unexpected exceptions

Do not log real app name, process name, or window title for excluded records.

Excluded records must be logged only as:

```text
status=excluded
```

or equivalent anonymized text.

---

## 9. Error Handling Principles

The app must follow these rules:

1. Collector errors must not crash the UI.
2. UI errors must not corrupt the database.
3. Database write errors must be logged.
4. Export errors must show a user-facing message.
5. Unexpected collector exceptions should set `collector_status = error`.
6. If collector enters error state, UI should show “状态异常”.
7. Recovery failures must be logged and shown in the UI.
8. No exception should silently fail without logging.

If an activity record cannot be trusted because of an error, mark it:

```text
status = error
```

---

## 10. Package Structure

Create this structure:

```text
worktrace/
│
├── main.py
├── config.py
├── constants.py
├── db.py
├── formatters.py
├── schema.sql
├── requirements.txt
├── README.md
├── architecture.md
│
├── collector/
│   ├── __init__.py
│   ├── collector.py
│   ├── state_machine.py
│   ├── heartbeat.py
│   └── single_instance.py
│
├── platforms/
│   ├── __init__.py
│   ├── base.py
│   ├── windows_adapter.py
│   └── fake_adapter.py
│
├── services/
│   ├── __init__.py
│   ├── activity_service.py
│   ├── project_service.py
│   ├── rule_service.py
│   ├── settings_service.py
│   ├── statistics_service.py
│   ├── recovery_service.py
│   ├── privacy_service.py
│   └── export_service.py
│
├── ui/
│   ├── __init__.py
│   ├── app.py
│   ├── timeline_view.py
│   ├── statistics_view.py
│   ├── settings_view.py
│   └── first_run_dialog.py
│
├── exports/
│   ├── __init__.py
│   ├── excel_exporter.py
│   └── markdown_exporter.py
│
├── templates/
│   └── weekly_report.md
│
└── tests/
    ├── test_state_machine.py
    ├── test_activity_service.py
    ├── test_rule_service.py
    ├── test_privacy_service.py
    ├── test_statistics_service.py
    ├── test_recovery_service.py
    └── test_export_service.py
```

---

## 11. SQLite Configuration

SQLite must be configured for local UI + collector access.

On connection initialization, execute:

```sql
PRAGMA journal_mode = WAL;
PRAGMA busy_timeout = 5000;
PRAGMA foreign_keys = ON;
```

Rules:

1. Collector writes must use short transactions.
2. UI reads must not hold long transactions.
3. All database writes must go through service functions.
4. Do not run multiple collectors against the same database.
5. If a database write fails, preserve collector state and surface the error in UI where possible.

---

## 12. Database Schema

Create `schema.sql` with the following schema.

```sql
CREATE TABLE IF NOT EXISTS project (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    description TEXT,
    is_archived INTEGER NOT NULL DEFAULT 0,
    created_by TEXT NOT NULL DEFAULT 'user' CHECK (
        created_by IN ('system', 'user')
    ),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS activity_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    start_time TEXT NOT NULL,
    end_time TEXT,
    duration_seconds INTEGER,
    app_name TEXT NOT NULL,
    process_name TEXT NOT NULL,
    window_title TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN ('normal', 'idle', 'paused', 'excluded', 'error')
    ),
    source TEXT NOT NULL CHECK (
        source IN ('auto', 'manual', 'system')
    ),
    is_deleted INTEGER NOT NULL DEFAULT 0,
    is_hidden INTEGER NOT NULL DEFAULT 0,
    auto_classified INTEGER NOT NULL DEFAULT 0,
    manual_override INTEGER NOT NULL DEFAULT 0,
    project_id INTEGER,
    note TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (project_id) REFERENCES project(id)
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_activity_time
ON activity_log(start_time, end_time);

CREATE INDEX IF NOT EXISTS idx_activity_status
ON activity_log(status);

CREATE INDEX IF NOT EXISTS idx_activity_project
ON activity_log(project_id);
```

Seed default settings:

```text
poll_interval_seconds = 3
idle_threshold_seconds = 300
current_activity_snapshot =
pending_short_seconds = 0
collector_status = stopped
last_collector_heartbeat =
last_shutdown_at =
first_run_notice_accepted = false
export_path = Documents\WorkTrace Exports
ui_refresh_seconds = 10
user_paused = false
context_carry_minutes = 15
```

The formal activity history threshold is a shared code constant fixed at 30 seconds. It is not stored in settings and is not configurable from the Settings page.

Seed default project:

```text
未归类
```

---

## 13. Settings Rules

`settings.value` is stored as text.

All type conversion must happen inside `settings_service.py`.

Other modules must not parse raw settings values directly.

Encoding rules:

```text
Boolean values: "true" / "false"
Integer values: base-10 string, e.g. "3"
String list values: comma-separated string
Paths: stored as resolved absolute paths after first resolution
Timestamps: local time string in "YYYY-MM-DD HH:MM:SS"
```

Required settings helpers:

```python
clear_settings_cache(key: str | None = None) -> None
get_setting(key: str, default: str | None = None) -> str | None
set_setting(key: str, value: str) -> None
get_bool_setting(key: str, default: bool = False) -> bool
get_int_setting(key: str, default: int) -> int
get_list_setting(key: str, default: list[str] | None = None) -> list[str]
set_list_setting(key: str, values: list[str]) -> None
```

---

## 14. Domain Concepts

### 14.1 Activity Status

`activity_log.status` must use these values:

```text
normal    Active normal window record
idle      User idle record
paused    User-paused collection state
excluded  Privacy-excluded anonymous time block
error     Recovered or inconsistent record requiring review
```

### 14.2 Source

`activity_log.source` must use these values:

```text
auto      created by collector
manual    created or materially edited by user
system    created by recovery or state transition logic
```

### 14.3 Review And Classification

Auto-created records are drafts. Users can organize records by editing project, note,
folder project rules, and keyword project rules.

### 14.4 Manual Override

`manual_override` prevents automatic rules from overwriting the user's choice.

Rules:

1. Auto-rules may apply only when `manual_override = 0`.
2. If user manually changes project, set `manual_override = 1`.
3. Auto-rule assignment sets `auto_classified = 1`.
4. Auto-rules must never overwrite `manual_override = 1`.

### 14.5 Project Inference Priority

Automatic project inference uses this priority:

```text
manual assignment
folder project rule
keyword rule
parent-folder suggested project name
uncategorized
```

Folder project rules prefer a known full file path or parent directory derived from the activity, but may fall back to the local folder-rule index when only a file name is visible. A known full local file path is an anchor regardless of extension. A file name without a path must not create a suggested project name from the file stem. Parent-folder suggested project names are limited to the built-in low-risk document extensions; user folder and keyword rules are not extension-limited. The folder-rule index stores file names and full paths for bound folders only, applies only after its `valid_from` time, and must not classify when the same title file name maps to different active projects.

The live current-activity snapshot must preview the same automatic inference priority without writing to history. Folder and keyword rules must be shown before parent-folder suggestions, so a file under a bound folder displays the project name immediately even before the 30-second persistence threshold.

Context carry-over may classify any normal auxiliary non-anchor activity. It uses the nearest previous and next anchor file activities only; an uncategorized anchor or an interrupt status stops the scan. Browsers, chat apps, meeting apps, editors, IDEs, and other apps use the same carry-over rules.

---

## 15. Platform Adapter Interface

Create `platforms/base.py`.

Define:

```python
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ActiveWindow:
    app_name: str
    process_name: str
    window_title: str
    file_path_hint: str | None = None


class PlatformAdapter(Protocol):
    def get_active_window(self) -> ActiveWindow:
        ...

    def get_idle_seconds(self) -> int:
        ...
```

`windows_adapter.py` must implement this interface using Windows APIs.

`fake_adapter.py` must implement deterministic fake data for tests.

The rest of the application must depend on `PlatformAdapter`, not directly on `pywin32`.

Windows active file path resolution order:

```text
window title full path
COM path catalog
foreground process open_files()
folder-rule file index
```

Full paths resolved by any source are stored as `file_path_hint` and may use any extension. The COM catalog is best-effort: use `GetActiveObject` only, filter built-in and user entries by registered ProgID, evaluate simple property / zero-argument method expressions, validate the result against the current window title, and silently fall back when lookup fails. The foreground `psutil` fallback must be attempted for any foreground process, not only Office/WPS, through a timeout-limited helper process. It must accept a path only when the title file name uniquely matches one open file basename, and a helper timeout must put that PID on a short cooldown so UI and collector threads cannot freeze on handle enumeration. The folder-rule index is the final fallback and must also return a path only when the indexed basename is unambiguous.

The built-in COM catalog should cover Office/WPS document apps, Acrobat/Reader, AutoCAD, Photoshop, Illustrator, InDesign, CorelDRAW, and SOLIDWORKS. Users may append entries through `%LOCALAPPDATA%\WorkTrace\com_path_catalog.json` with this shape:

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

---

## 16. Collector State Machine

### 16.1 Collector Runtime States

Internal collector states:

```text
recording
idle
paused
excluded
stopped
error
```

Database record statuses:

```text
normal
idle
paused
excluded
error
```

Mapping:

```text
recording → normal
idle      → idle
paused    → paused
excluded  → excluded
error     → error
```

### 16.2 State Transition Rule

Every state transition must follow:

```text
close previous open record
→ compute duration
→ persist previous record
→ open next record if needed
```

There must never be more than one open `activity_log` row with `end_time IS NULL`.

### 16.3 Transition Examples

Normal window to idle:

```text
normal Word record open
→ user idle threshold exceeded
→ close Word record
→ open idle record
```

Idle to normal window:

```text
idle record open
→ user active again
→ close idle record
→ open current normal window record
```

Normal to excluded:

```text
normal Word record open
→ active window matches exclude keyword
→ close Word record
→ open excluded anonymous record
```

Excluded to normal:

```text
excluded record open
→ active window no longer excluded
→ close excluded record
→ open normal record
```

Normal to paused:

```text
normal record open
→ user clicks pause
→ close normal record
→ open paused record or enter paused state
```

Paused to normal:

```text
paused record open
→ user clicks resume
→ close paused record
→ open current normal window record
```

### 16.4 Sleep / Time Jump Handling

Track the previous collector loop timestamp.

If:

```text
now - last_loop_time > idle_threshold_minutes
```

then:

1. close current open record at `last_loop_time` if safe;
2. keep the next record available for user review;
3. if duration cannot be trusted, set `status = error`.

---

## 17. Collector Loop

Implement in `collector/collector.py`.

Pseudo-code:

```python
def run_collector(adapter: PlatformAdapter, stop_event: threading.Event) -> None:
    ensure_single_instance()
    recover_unclosed_records()
    set_collector_status("running")

    while not stop_event.is_set():
        try:
            update_heartbeat()

            if not first_run_notice_accepted():
                transition_to("paused")
                sleep_poll(stop_event)
                continue

            if user_paused():
                transition_to("paused")
                sleep_poll(stop_event)
                continue

            active_window = adapter.get_active_window()
            idle_seconds = adapter.get_idle_seconds()

            if idle_seconds >= idle_threshold_seconds():
                transition_to("idle")
                sleep_poll(stop_event)
                continue

            if privacy_service.is_excluded(active_window):
                transition_to("excluded")
                sleep_poll(stop_event)
                continue

            transition_to("recording", active_window)
            sleep_poll(stop_event)

        except Exception:
            log_exception()
            set_collector_status("error")
            sleep_poll(stop_event)

    close_current_open_record()
    set_collector_status("stopped")
```

Polling interval:

```text
settings.poll_interval_seconds
default = 3
```

---

## 18. Single Instance Control

Implement in `collector/single_instance.py`.

Preferred approach on Windows:

```text
Windows Mutex
```

Fallback approach:

```text
lock file + heartbeat stale check
```

Requirements:

1. Only one collector may write to the database.
2. If a second app instance opens, it may show UI but must not start a second collector.
3. If stale lock file exists and heartbeat is old, user may recover.
4. Lock must be released on graceful shutdown.

---

## 19. Heartbeat and Recovery

### 19.1 Heartbeat

Every 10–30 seconds, write:

```text
collector_status = running
last_collector_heartbeat = current local timestamp
```

UI must display one of:

```text
记录中
已暂停
采集器未运行
状态异常
```

### 19.2 Recovery on Startup

On startup:

1. check for activity rows where `end_time IS NULL`;
2. if found, use `last_collector_heartbeat` as `end_time` where available;
3. otherwise use current startup time and mark `status = error`;
4. split non-error recovered records at local midnight when needed;
5. compute `duration_seconds`;
6. show such records as needing user review.

---

## 20. Exclude Rules

### 20.1 Special Project

WorkTrace seeds a disabled system project named `排除规则`. It is displayed on the Project Rules page and supports the same three rule kinds as ordinary projects. It starts with no default rules; users enable it and add any file, folder, or keyword exclusions they want.

```text
folder
file
keyword
```

When an active window matches this project, the collector records an anonymous `excluded` activity payload instead of storing the real title or path.

### 20.2 Matching Fields

Check keyword exclude rules against:

```text
app_name
process_name
window_title
file_path_hint
```

### 20.3 Excluded Record Behavior

If excluded:

1. do not store real app name;
2. do not store real process name;
3. do not store real window title;
4. store anonymous placeholder data.

Use:

```text
app_name = 已排除
process_name = excluded
window_title = 已排除窗口
status = excluded
```

Excluded records are not exported by default.

---

## 21. First-Run Privacy Notice

On first launch, before starting collection, show a privacy dialog.

Required text:

```text
WorkTrace 将在本机记录：
- 当前活动应用名称
- 当前窗口标题
- 使用开始时间、结束时间和持续时间

WorkTrace 不会记录：
- 键盘输入
- 鼠标点击内容
- 屏幕截图或录屏
- Word、PDF、网页、邮件正文
- 浏览器历史、Cookie 或密码

所有数据默认保存在本机，不上传到云端。

自动记录只是工作轨迹草稿，最终工时应由用户按需整理和归类。
```

Rules:

1. Collection must not start before user acceptance.
2. On acceptance, set:

```text
first_run_notice_accepted = true
```

3. Settings page must allow user to view the notice again.
4. If collection scope changes in future versions, the notice must be shown again.

---

## 22. Rule-Based Auto Classification

### 22.1 Rule Matching

A rule has:

```text
keyword
project_id
enabled
```

Match keyword against:

```text
window_title
app_name
process_name
file_path_hint
```

### 22.2 Conflict Handling

v0.1 Lite does not implement complex priority.

If multiple enabled rules match:

```text
use the earliest created enabled rule
```

### 22.3 Manual Override

Auto-classification must run only when:

```text
manual_override = 0
```

If user changes project manually:

```text
manual_override = 1
```

### 22.4 Folder Rules And Suggested Names

Folder project rules match only anchor file activities with a recognized full path or parent directory. Recognized full local paths are anchor files regardless of extension. Windows adapters should resolve paths through the COM catalog and may fall back to the foreground process open-file list for any process when the window title has a unique exact file-name match.

Suggested project names are display-only Time Details hints. They may be derived from a known non-generic parent folder name only when the file extension is in the built-in automatic-project extension list, and must not be derived from a bare file name or file stem.

### 22.5 Reporting Context Merge

Time Details sessions and project statistics use an in-memory reporting project in addition to the raw activity project.

If two anchors for project A enclose a contiguous block under 5 minutes containing only a different normal project or idle records, count that block under A for the Time Details session and project statistics.

This reporting merge must not update `activity_log.project_id`, `activity_project_assignment`, the raw status, or the detailed activity rows.

The reporting merge is only a supplement to existing context rules. If the enclosing A anchors exceed `context_carry_minutes`, do not merge the block.

If a short activity is absorbed into the previous persisted normal activity and the same activity signature resumes immediately afterward, the recorder must reopen and continue the previous persisted row instead of creating a second row for the same activity.

### 22.6 Report Dates Across Midnight

Report views use an in-memory `report_date`, not only `activity_log.start_time`.

All rows are split at local midnight and counted on their calendar date. This applies to Overview, Time Details, Statistics, and range exports that consume reporting summaries.

When the collector itself crosses midnight during a concrete normal project, close the pre-midnight activity at `00:00:00`, record a `session_boundary` with reason `midnight`, and start a new activity at `00:00:00`.

If the new post-midnight activity would otherwise be uncategorized or shorter than the 30-second history threshold, persist it immediately with an automatic `midnight_anchor` assignment to the previous concrete project. This assignment must not set `manual_override`, update folder rules, update keyword rules, or create any long-term per-file binding. It may act as a context anchor for subsequent auxiliary activity.

If the previous activity has no existing concrete project, do not create a suggested project and do not apply `midnight_anchor`.

---

## 23. Services

### 23.1 activity_service.py

Responsible for activity CRUD.

Required functions:

```python
create_activity(...)
close_activity(activity_id: int, end_time: str) -> None
get_open_activity() -> dict | None
get_activities_by_date(date: str) -> list[dict]
get_activities_by_range(start_date: str, end_date: str) -> list[dict]
update_activity_project(activity_id: int, project_id: int, manual: bool = True) -> None
update_activity_note(activity_id: int, note: str) -> None
soft_delete_activity(activity_id: int) -> None
```

### 23.2 project_service.py

Required functions:

```python
create_project(name: str, description: str = "") -> int
list_active_projects() -> list[dict]
archive_project(project_id: int) -> None
get_or_create_uncategorized_project() -> int
```

### 23.3 rule_service.py

Required functions:

```python
create_rule(keyword: str, project_id: int) -> int
list_rules() -> list[dict]
set_rule_enabled(rule_id: int, enabled: bool) -> None
delete_rule(rule_id: int) -> None
apply_rules_to_activity(activity_id: int) -> None
apply_rules_to_unclassified() -> None
```

Folder-rule and keyword-rule lookup paths may keep short TTL caches keyed by the active database path. Creating, deleting, enabling, or disabling a rule must invalidate the relevant cache.

### 23.4 settings_service.py

Required functions:

```python
clear_settings_cache(key: str | None = None) -> None
get_setting(key: str, default: str | None = None) -> str | None
set_setting(key: str, value: str) -> None
get_bool_setting(key: str, default: bool = False) -> bool
get_int_setting(key: str, default: int) -> int
get_list_setting(key: str, default: list[str] | None = None) -> list[str]
set_list_setting(key: str, values: list[str]) -> None
```

`settings_service` may keep a short TTL in-memory cache, but cache keys must include the active database path. `set_setting` must update the cache for the written key.
Privacy exclusion keywords may cache the parsed list by database path; `set_exclude_keywords` must update or invalidate that cache.

### 23.5 statistics_service.py

Required functions:

```python
get_summary(start_date: str, end_date: str) -> dict
get_project_stats(start_date: str, end_date: str, ensure_context: bool = True) -> list[dict]
get_uncategorized_duration(start_date: str, end_date: str) -> int
```

`get_summary` returns `classified_duration` in addition to total, effective, idle, paused, excluded, and uncategorized durations.
`get_summary` should ensure context assignments once for the requested range, then compute status totals with SQL aggregation and call project stats without repeating context recomputation.

Per-date context recomputation should keep an in-memory fingerprint cache keyed by database path and date. If the relevant activity, assignment, project, folder-rule, keyword-rule, and context-setting fingerprint is unchanged, repeated Overview/Time Details/Statistics refreshes must skip the scan-and-write recomputation path.

### 23.6 recovery_service.py

Required functions:

```python
recover_unclosed_records() -> None
detect_time_jump(last_loop_time: str, now: str) -> bool
mark_record_error(activity_id: int, reason: str) -> None
```

### 23.7 privacy_service.py

Required functions:

```python
get_exclude_keywords() -> list[str]
set_exclude_keywords(keywords: list[str]) -> None
is_excluded(active_window: ActiveWindow) -> bool
make_excluded_activity_payload() -> dict
```

### 23.8 export_service.py

Required functions:

```python
export_excel(start_date: str, end_date: str, path: str) -> str
export_markdown(start_date: str, end_date: str, path: str) -> str
export_all_local_data(path: str) -> str
clear_all_local_data(confirm: bool) -> None
```

---

## 24. UI Requirements

Use 5 pages:

1. Overview
2. Time Details
3. Statistics and Export
4. Project Rules
5. Settings and Privacy

The collector thread must not directly update UI widgets. UI must refresh via Tkinter `after()` polling.
Pages are created lazily on first visit, then stay mounted in the shell and switch with `tkraise()` to avoid visible re-creation flicker. Full data refreshes should be incremental where possible; live current-activity labels and visible durations are refreshed by the app shell every 1 second without rebuilding page content. Time Details must use value-only Treeview updates while session/detail structure is stable, falling back to one full refresh when rows are added, removed, or reordered. Resize and restore use separate visual-suspend strategies: resize may temporarily unmap the content area under a content cover, while restore keeps content mounted under a full-window cover and defers heavy refresh until after reveal.

Default refresh interval:

```text
10 seconds
1 second for live current-activity and duration values
```

### 24.1 Overview Page

Must show:

1. total duration
2. classified duration
3. uncategorized duration
4. current activity
5. recent sessions

Only the recent sessions area should scroll. Clicking uncategorized duration opens Time Details filtered to uncategorized sessions. Clicking a recent session opens Time Details with that session selected.

### 24.2 Time Details Page

Must show:

1. collector status
2. pause / resume button
3. date selector
4. project session table
5. detail activity table
6. adjustment panel for selected detail activity rows
7. note editor for single detail activity rows
8. delete action
9. filters for uncategorized records
10. current activity with a live `hh:mm:ss` counter

The page exposes `open_context(target_date, only_uncategorized=False, selected_session_id=None)` so other pages can open it with a date, filter, and selected session.

Time Details must not expose manual session splitting, same-name project segment merge, cross-project session merge, or moving a detail activity into another session. Project correction targets are limited to the selected project session or the selected detail activity.

The detail activity table is the only activity-level view. File identity is derived from each activity at runtime from app name, process name, window title, and file path hint; the UI must not expose a separate persisted-file view or a per-file default binding.

The detail activity project selector must list selectable projects only. It must not add current session rows or other session targets, because that reintroduces cross-session merge behavior and can create large menus on busy days.

Columns:

```text
Time range
Status
App name
Window title
Duration
Project
Note
Actions
```

### 24.3 Statistics and Export Page

Must show:

1. date range selector
2. total duration
3. effective work duration
4. idle duration
5. excluded duration
6. uncategorized duration
7. project stats table
8. export Excel button

Project stats use the reporting context merge and report-date assignment. Total, effective, idle, excluded, and paused summary durations use raw activity status but the same report-date slicing and live open-record duration projection.

### 24.4 Project Rules Page

Must show:

1. project binding overview
2. project rules list
3. top-level add-project action
4. per-project add-rule actions

Project rules include folder rules and keyword rules. Folder and keyword rules support enable, disable, and delete.

The top-level action is labeled `新增项目` and opens project creation by default. Each project card exposes `新增规则`, which opens rule creation with that project preselected.

### 24.5 Settings and Privacy Page

Must show:

1. export path
2. view first-run notice
3. clear all local data

The Settings and Privacy page must not show the removed `关于本地数据` section, including database path, log path, collector heartbeat, or version details.

---

## 25. Export Requirements

### 25.1 Excel Export

Use `openpyxl`. Import it lazily inside export functions so startup and non-export UI paths do not load the workbook stack.

Export two sheets.

Sheet 1: `Summary`

Columns:

```text
Project
Total Duration
Record Count
```

Summary durations are formatted as `hh:mm:ss` and use project statistics after reporting context merge.
Shared duration formatting must live in `worktrace.formatters`; UI modules must not import `markdown_exporter` just to format durations. `markdown_exporter` may re-export the formatter functions for compatibility.

Sheet 2: `Activity Logs`

Columns:

```text
Date
Start Time
End Time
Duration
Status
App Name
Window Title
Project
Note
```

Activity log durations are formatted as `hh:mm:ss`. Activity log rows preserve raw status and project assignment.

Default export filtering:

1. include `normal` records;
2. exclude `idle`;
3. exclude `paused`;
4. exclude `excluded`;
5. exclude `is_deleted = 1`;
6. exclude `is_hidden = 1`;

### 25.2 Markdown Weekly Draft

Use template:

```markdown
# WorkTrace 周报草稿

周期：{{ start_date }} 至 {{ end_date }}

## 一、本周时间概览

总记录时长：{{ total_duration }}  
有效工作时长：{{ effective_duration }}  
空闲时间：{{ idle_duration }}  
排除时间：{{ excluded_duration }}  
未归类时间：{{ uncategorized_duration }}  

## 二、项目投入情况

{{ project_summary }}

## 三、项目明细

{{ project_details }}

- 未归类记录：
{{ uncategorized_records }}

- 已排除时间：
{{ excluded_summary }}

- 下周计划：
```

---

## 26. Data Clearing and Local Data Export

### 26.1 Clear Local Data

Settings page must include:

```text
清空所有本地记录
```

Before clearing, require confirmation:

```text
此操作将删除本机保存的所有工作轨迹、项目、规则和设置。删除后无法恢复。是否继续？
```

Implementation may delete and recreate the SQLite database or clear all tables and reseed defaults.

### 26.2 Export All Local Data

The UI does not expose export-all-local-data. Settings only supports clearing all local records; reporting views expose range Excel export. The Markdown exporter remains available as a service/API helper.

---

## 27. Time Handling

### 27.1 Format

Use local time in ISO-like format:

```text
YYYY-MM-DD HH:MM:SS
```

v0.1 Lite does not support cross-timezone sync.

### 27.2 Duration

Compute:

```text
duration_seconds = end_time - start_time
```

Rules:

1. Duration must never be negative.
2. If negative, set status to `error`.
3. If a single normal record exceeds 4 hours, keep it and show it for user review.
4. If system sleep or large time jump is detected, close the previous record and keep the next relevant record available for user review.
5. Persist normal, idle, paused, excluded, and error segments once they reach 30 seconds.
6. Display all stored durations as exact `hh:mm:ss` without minute rounding.
7. Display the current activity counter as `hh:mm:ss`.
8. Persisted activity durations must be monotonic: live projections, `extra_seconds`, close operations, and recovery must never reduce an already stored duration.
9. Update visible Overview KPI durations, Time Details session/detail durations, and Statistics durations every second from the current activity snapshot without requiring a full page refresh.
10. While a new current activity is still below the 30-second history threshold, only the Overview recent-project row and Time Details project/session row temporarily carry those seconds on the previous confirmed project. The current-activity label, KPI summaries, Statistics, and activity details keep using the real current snapshot, and that snapshot must preview folder/keyword project rules before falling back to parent-folder suggestions.
11. Suspend heavy page refresh and live duration updates while the root window is actively resizing or minimized. Resize uses a stable content-area cover and can run one catch-up refresh before reveal. Restore uses a full-window cover, keeps the content tree mounted, reveals the complete UI first, then runs one delayed merged refresh.
12. On Windows, rely on Tk `<Unmap>`, `<Map>`, and `<Configure>` events for minimize/restore handling. Native WndProc subclassing is disabled to avoid Python runtime/GIL crashes.

---

## 28. README Requirements

README must include:

1. project summary
2. core features
3. portable usage
4. startup instructions
5. permission statement
6. privacy statement
7. local database path
8. export path
9. current limitations
10. collector heartbeat explanation
11. abnormal recovery explanation
12. single-instance explanation
13. uninstall instructions
14. data clearing instructions

README must explicitly say:

```text
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
```

---

## 29. Acceptance Criteria

### 29.1 Functional Acceptance

The app is acceptable if:

1. It runs on Windows.
2. It runs without administrator privileges.
3. It does not require network.
4. It does not require account registration.
5. It shows first-run privacy notice.
6. It does not collect before notice acceptance.
7. It records active window metadata.
8. It records start time, end time, duration.
9. It detects idle time.
10. It anonymizes excluded windows.
11. It shows daily Time Details.
12. It allows project creation.
13. It allows assigning records to projects.
14. It allows notes.
15. It summarizes time by project.
16. It exports Excel.
17. It keeps Markdown export available outside the visible UI.
20. It supports exclude keywords.
21. It supports pause / resume.
22. It supports soft delete.
23. It supports local data clearing.
24. It supports local data export.
25. It shows collector heartbeat.
26. It recovers unclosed records.
27. It prevents multiple collectors.
28. UI remains responsive while collector runs.
29. App exits cleanly and closes current open record.

### 29.2 Privacy Acceptance

The app is acceptable only if:

1. no account registration;
2. no network required;
3. no admin privilege request;
4. no screenshot;
5. no screen recording;
6. no keyboard input recording;
7. no mouse-click content recording;
8. no file body reading;
9. no webpage body reading;
10. no email body reading;
11. no data upload;
12. excluded windows do not save real title;
13. user can clear the local database;
14. collection does not start before first-run notice acceptance.

### 29.3 State Machine Acceptance

The state machine is acceptable if:

1. normal / idle / paused / excluded transitions do not leave duplicate open records;
2. each state transition closes previous open record;
3. pause stops real window title recording;
4. resume restarts current window recording;
5. excluded state never saves real window title;
6. abnormal shutdown is recovered on next startup;
7. negative duration becomes `error`;
8. unusually long records remain visible for user review.

---

## 30. Tests

Implement pytest tests for:

1. state transitions
2. idle transition
3. excluded transition
4. pause / resume transition
5. recovery of open record
6. rule auto-classification
7. manual override preventing rule overwrite
8. privacy keyword matching
9. statistics aggregation
10. Excel export file creation
11. Markdown service export content
12. settings read / write
13. single-instance lock behavior where feasible
14. collector loop using fake adapter
15. UI-independent service behavior

Tests must not require real Windows foreground windows. Use `fake_adapter.py`.

---

## 31. Security and Packaging Notes

PyInstaller-built Windows apps may trigger SmartScreen or antivirus warnings, especially because WorkTrace observes active window metadata.

The app must reduce risk by:

1. not hiding its window;
2. not auto-starting by default;
3. not installing a service;
4. not installing drivers;
5. not requesting administrator rights;
6. not reading sensitive body content;
7. not uploading data;
8. showing clear privacy notice;
9. documenting collection scope in README.

Code signing is not required for v0.1 Lite but should be considered before public release.

---

## 32. Definition of Done

v0.1 Lite is done when:

```text
A user can launch the portable Windows app,
accept the first-run privacy notice,
record active window metadata locally,
see Time Details,
pause and resume recording,
handle idle and excluded windows correctly,
classify records into projects,
add notes,
view project statistics,
export an Excel timesheet from the UI,
generate a Markdown weekly draft through the service/API,
and clear or export all local data,
without registration, network access, administrator privileges, screenshots, keyboard logging, content reading, or data upload.
```
