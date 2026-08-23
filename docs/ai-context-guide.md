# AI Context Guide

> Conventions for AI assistants (and developers) working in this repository.
> Goal: keep each iteration fast and low-token by reading only what the
> current task needs.

## 1. Default Reading Order

For any new task, default to this minimal reading order:

1. [`docs/current-state.md`](current-state.md) — the one-screen "what ships
   today" snapshot. **Start here.** It is the single source of truth for
   current shipped behavior.
2. [`architecture.md`](../architecture.md) — read this for architecture,
   boundary, live-display ownership, lifecycle, export-surface, startup, or
   cross-layer cleanup tasks. It is the current architecture contract.
3. [`docs/ui-webview-migration.md`](ui-webview-migration.md) — only the
   historical WebView migration decisions and migration principles. The
   migration is closed; do not treat this file as the current architecture
   owner when it conflicts with `architecture.md` or `current-state.md`.
4. The specific source files your task touches.

For display-model hardening, the default touched-file neighborhood is:
`worktrace/services/activity_display_model_service.py`,
`activity_display_policy.py`, `activity_live_clock.py`,
`activity_display_span.py`, `activity_row_overlay.py`,
`view_model_service.py`, `live_display_service.py`, `live_time_service.py`,
the collector lifecycle files involved in the change, affected WebView JS,
and the focused live-display tests. Do not expand beyond this set unless a
test failure or unclear boundary requires it.

Do **not** default-read the full README, the phase history, the release
validation doc, or research docs. Reach for them only when the task actually
needs them.

## 2. Where The History Lives

- [`docs/history/webview-phases.md`](history/webview-phases.md) — the long-form
  Phase 0A → current WebView phase log. Read it **only** when you need the
  exact data semantics or "not implemented" list of a specific past phase.
- [`docs/release-validation.md`](release-validation.md) — the canonical release
  baseline. Read it **only** when validating a release.

Treat these as archives, not as default context.

## 3. Documentation Governance

The repository follows a single-source-of-truth documentation model:

- **README** is a project overview and should not carry long phase chronology.
- **`docs/current-state.md`** is the current shipped behavior source.
- **`architecture.md`** is the current architecture contract.
- **`docs/ui-webview-migration.md`** is migration history, not a current architecture owner.
- **`docs/history/webview-phases.md`** is the closed migration archive.
- **`docs/release-validation.md`** is the release baseline.
- Ordinary maintenance does not create new migration phases. Update `current-state.md` only when shipped behavior changes and `architecture.md` when an architecture contract changes.
- **`docs/release-checklist.md`** is only a compatibility pointer to `docs/release-validation.md`.

## 4. Research Docs

- Research / scan docs live under [`docs/research/`](research/). They are not default context.
- Read them only when the task explicitly concerns that research topic.
- Current shipped behavior always comes from `docs/current-state.md`.

## 5. Task Prompt Hygiene

Each task prompt / plan should state explicitly:

- **Goal files**: the exact files the task will modify.
- **Allowed reads**: the files the agent may read to do the job.
- **No broad scans**: do not scan the whole repo merely to understand it unless the task is genuinely exploratory. Targeted search on a known directory is fine.

## 6. When To Expand Search

Expand beyond the minimal set only when:

- a test fails and the cause is not in the touched files;
- a boundary or contract is unclear from `current-state.md` and `architecture.md`;
- the task explicitly references historical semantics.

WorkTrace has not shipped a public compatibility surface for internal display-model modules, payload fields, tests, or developer-only scripts. Remove unused aliases, stale import paths, wrappers, and compatibility shims when all current callers/tests can be updated in the same change.

## 7. Context Diet Cadence

Periodically:

- ensure `current-state.md` matches shipped behavior;
- ensure `architecture.md` matches current owner boundaries;
- move accumulated chronology out of current docs and into history when it is genuinely historical;
- split or parameterize test files that accumulate unrelated scenarios or duplicated static contracts;
- keep the default reading set small.

## 8. Don't Break The Boundaries

When editing docs or tests, never weaken the hard constraints in project memory: WebView bridge may only import `worktrace.api`; no external links / CDN / Google Fonts / `localStorage` in frontend resources; no tracebacks to JS; `schema.sql` is the single source of DB structure; and docs/tests-only work must not introduce product features or runtime dependencies.

## 9. Test Selection

Keep local feedback explicit rather than maintaining an inferred changed-file dependency graph.

- For a known owner/regression, run the specific test file or case.
- For fast feedback, use `python -m pytest -m "unit and not slow"`.
- For cross-layer/static contracts, use `python -m pytest -m contract` or a narrower marker expression such as `webview_static and contract`, `live_display and contract`, `collector_runtime and integration`, or `security_privacy`.
- For a known failure, prefer `python -m pytest --lf`.
- For cross-cutting/pre-push confidence, use `python -m pytest -m "not benchmark"`.
- Standard CI always runs the complete non-benchmark Python suite; local selection never replaces that gate.
- Marker names live only in `pytest.ini`, which enables strict marker validation.
- Do not introduce a custom affected-test scheduler, source-string risk classifier, test owner registry, or CI file-size budget layer.
- PyInstaller/installer lifecycle and performance/timing validation stay in their dedicated workflows.
- Parallel pytest is not enabled; `parallel_safe` and `serial` remain planning labels only.

See [`docs/testing/test-governance.md`](testing/test-governance.md) for test-maintenance rules and [`docs/release-validation.md`](release-validation.md) for the release baseline.

## 10. Comment Hygiene Gate

After each AI coding pass, run `python scripts/comment_hygiene.py --check`.
If it fails, use `python scripts/comment_hygiene.py --json` together with
[`.ai/comment-hygiene-fixer.md`](../.ai/comment-hygiene-fixer.md) to fix it.
Do not add historical migration narratives or comments that restate nearby code.
