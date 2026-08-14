# CI Governance

WorkTrace CI is intentionally split by validation cost and responsibility.

## Standard CI

`CI` runs for every pull request and every push to `main`. It is the merge-time correctness gate and keeps three parallel Windows jobs:

- the full Python 3.11 non-benchmark suite plus Python compilation;
- WebView Node behavior, the FD Work Edge DOM fixture, and typography acceptance on the same UI runner;
- a build-only Windows package smoke that verifies `Trace.exe` and `Trace-Setup.exe` can be produced.

Pytest owns collection and marker validation. `pytest.ini` enables strict markers, and Standard CI runs the full non-benchmark suite rather than relying on a custom test inventory or affected-test scheduler.

Standard CI must not install, upgrade, or uninstall the packaged application. Those lifecycle checks are intentionally isolated so ordinary product changes do not pay release-level runtime cost on every commit.

The Python diagnostic artifact contract in `_validation.yml` remains the canonical failure-diagnostics path and must not be weakened when changing orchestration.

## Installer validation

`Installer validation` owns packaged runtime lifecycle acceptance:

- fresh per-user installation;
- startup Run-value behavior;
- launch of the installed executable;
- upgrade while the current executable is running;
- cleanup of the legacy `WorkTrace.exe` compatibility path;
- preservation of enabled startup state across upgrade;
- uninstall while Trace is running;
- cleanup of the startup value.

It runs automatically on every push to `main`, on release tags matching `v*`, and on pull requests that touch installer/package/runtime-sensitive paths. It can also be dispatched manually against an exact commit SHA.

Both Standard CI package smoke and Installer validation use `.github/actions/build-windows-package` so package construction has one implementation.

## Performance validation

`Performance validation` remains an opt-in or scheduled product-performance gate. It is not part of ordinary Standard CI.

## Standard timing validation

`Standard timing validation` remains an opt-in baseline-vs-HEAD test-suite timing gate. It is separate from product performance because the two workflows answer different regression questions.

## Policy

Keep the core correctness suite full. Local development may use an explicit test file/case or a pytest marker shard, but merge-time validation must not infer tests from changed paths.

Reduce CI cost by isolating genuinely expensive domain-specific acceptance, not by silently reducing correctness coverage. Do not create a generic smart-CI scheduler or a second machine-readable test policy that duplicates pytest and workflow configuration. Shared automation should be extracted only when the responsibility is stable and genuinely reused, as with Windows package construction.
