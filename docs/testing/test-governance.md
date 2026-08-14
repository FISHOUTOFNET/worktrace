# Test Governance

WorkTrace keeps local test selection explicit and keeps Standard CI complete. The test system must protect current product behavior, durable compatibility requirements, data integrity, security/privacy boundaries, concurrency/recovery behavior, and stable architecture boundaries without building a second dependency scheduler on top of pytest.

## Entrypoints

```powershell
# Known area or regression
python -m pytest tests/test_timeline_service.py
python -m pytest --lf

# Fast marker-covered feedback
python -m pytest -m "unit and not slow"

# Cross-layer/static contracts
python -m pytest -m contract

# Same Python correctness surface used by Standard CI
python -m pytest -m "not benchmark"
```

Developers should choose an explicit test file/case when the owner is known, or use a marker shard when a feature spans several files. There is no affected-test dependency map. Standard CI always runs the complete non-benchmark Python suite, so local test selection is an iteration aid rather than a merge-safety mechanism.

## Marker Policy

Markers are registered once in `pytest.ini`. Pytest runs with `--strict-markers`, so misspelled or undeclared markers fail through pytest itself instead of a separate inventory tool.

Use markers for meaningful execution characteristics or stable test surfaces:

- `unit`: pure function or single-service behavior without real runtime/packaging flow.
- `db`: SQLite, migration, transaction, or data-loss boundaries.
- `integration`: cross-service, API, bridge, runtime, or subprocess behavior.
- `contract`: API/payload/static/stable boundary contracts.
- `webview_static`: static HTML/CSS/JS source-reading contracts.
- `live_display`: current/recent/timeline/details/KPI live-display semantics.
- `collector_runtime`: collector/runtime/thread/control-channel behavior.
- `security_privacy`: encryption, backup, privacy, exclusion, or leak prevention.
- `packaging`: executable/installer/release packaging checks.
- `slow`: intentionally high-runtime tests.
- `benchmark`: performance tests excluded from Standard CI.
- `parallel_safe` / `serial`: planning labels only; parallel pytest is not enabled.

Do not infer required markers by scanning source strings such as `threading`, `sqlite`, or `subprocess`. Such scans generate false positives and duplicate information already visible in the test itself.

## Test Retirement And Maintenance

Tests protect current behavior; they are not permanent records of how a refactor was completed.

- Remove Stage/Phase/checkpoint tests after cutover when their only purpose is proving that an old implementation disappeared.
- Do not retain repository-wide blacklists of retired private names, old state labels, old error strings, or old workflow shapes unless reintroducing that exact construct would violate a current public, safety, or security contract.
- Do not test how other tests are written unless the rule is required for test correctness. Stable WebView static-test hygiene is an exception because collection-time mutation and fixed-window source slicing previously caused false test results.
- Prefer one owner test for a stable boundary over several overlapping source scans.
- Preserve old-version cases when they exercise a current compatibility or fail-safe policy, such as rejecting an incompatible database without data loss.
- When a historically named test still covers current behavior, move the behavior into the current owner suite and rename it rather than dropping coverage.
- CI/timing/performance harness tests should validate stable interfaces and failure modes, not mirror workflow YAML line-by-line.

When deleting a test, verify that any unique behavior it protected is already covered by a current owner test. No selector map, owner registry, risk-string database, or file-size exception list needs to be updated.

## New Test Admission

- Prefer pure policy/function tests before DB tests.
- Prefer service behavior before bridge/runtime behavior.
- Prefer model assertions before real file write/read tests.
- Prefer fake clocks or injected waits over real wall-clock sleeps.
- Use parameterized matrices for repeated validation/error-boundary cases.
- Add architecture tests only for stable invariants and name the invariant they protect.
- Split a test file when its scenarios no longer share one behavioral owner; do not enforce arbitrary line-count budgets through CI.
- Keep PyInstaller/installer lifecycle and benchmarks in their dedicated validation paths rather than ordinary local feedback.

Run the full non-benchmark suite before relying on a cross-cutting change involving DB/schema, collector/runtime, live-display semantics, export/privacy/security, recovery/concurrency, or broad architecture ownership. Standard CI performs this full run on every PR regardless of local selection.
