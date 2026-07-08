# Test Governance

WorkTrace keeps day-to-day feedback narrow while preserving the full pytest
suite as the regression backstop. Do not remove or weaken tests for the core
product semantics to make a command faster: live Current / Recent / Timeline /
KPI consistency, 30s short-activity persistence boundaries, idle / paused /
excluded / error behavior, attribution, CSV / display labels, privacy, backup,
and DB migration coverage remain protected.

## Daily Entrypoints

```powershell
python scripts/run_affected_tests.py
python scripts/run_affected_tests.py --fast
python scripts/run_affected_tests.py --governance
python -m pytest -m contract
pytest
```

- `affected`: default development path. It maps changed files to concrete
  pytest targets and never silently runs the full suite.
- `fast`: marker-covered fast feedback, currently
  `python -m pytest -m "unit and not slow"`. Marker coverage is incremental,
  so this is not a complete fast universe yet.
- `governance`: inventory check, comment hygiene, and focused runner /
  inventory governance tests.
- `contract`: API, ViewModel, static frontend, payload, and boundary
  contracts.
- `full`: complete regression suite for DB/schema, collector/lifecycle,
  display model, export/privacy/security, release validation, or pre-push
  confidence.

## Markers

- `unit`: pure function or single-service tests without DB, threads, GUI, or
  packaging flow.
- `db`: temp DB, `get_connection`, SQLite, migration, or data-loss boundary.
- `integration`: cross-service, API, bridge, runtime, or subprocess behavior.
- `contract`: API/payload/static/boundary contract.
- `webview_static`: static HTML/CSS/JS source-reading tests.
- `live_display`: current/recent/timeline/details/KPI live display semantics.
- `collector_runtime`: collector loop, runtime startup, pause/resume, idle,
  thread, or control-channel behavior.
- `security_privacy`: encryption, backup, privacy, excluded/anonymized data,
  or sensitive leak checks.
- `packaging`: PyInstaller, installer, release docs/spec smoke tests.
- `slow`: intentionally high-runtime tests.
- `parallel_safe` / `serial`: future-planning labels only; parallel pytest is
  not enabled.

## Owner And Budget Rules

`test_policy.json` records suite intent, file budgets, risk signals, marker
requirements, and owner/contract paths. A test file over the line or test-count
budget must have an override with a reason. New large tests should usually be
split by owner or expressed as a parameterized matrix.

Owner areas include live display, collector lifecycle / 30s short activity,
timeline editing, project rules, statistics/export, security/privacy/backup,
WebView static/frontend render, DB/migration, and governance.

## New Test Admission

- Prefer pure function/policy tests before DB tests.
- Prefer service tests before bridge/runtime tests.
- Prefer export model assertions before real file write/read tests.
- Prefer fake clocks or injected waits; do not use real `time.sleep`.
- Use parameterized matrices for repeated validation and error-boundary cases.
- Mark DB, runtime/threading, subprocess, WebView static, and live-display tests
  according to `test_policy.json`.
- Keep PyInstaller and installer builds out of the affected runner.

Run full `pytest` when a change crosses owner boundaries, touches DB/schema,
collector/lifecycle/live display semantics, export/privacy/security, packaging
release behavior, or when marker coverage does not confidently select the
right regression surface.
