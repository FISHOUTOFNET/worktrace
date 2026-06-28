# AI Context Guide

> Conventions for AI assistants (and developers) working in this repository.
> Goal: keep each iteration fast and low-token by reading only what the
> current task needs.

## 1. Default Reading Order

For any new task, default to this minimal reading order:

1. [`docs/current-state.md`](current-state.md) — the one-screen "what ships
   today" snapshot. **Start here.** It is intentionally ≤ 150 lines.
2. [`docs/ui-webview-migration.md`](ui-webview-migration.md) — only the
   architecture decisions and migration principles (now slim).
3. The specific source files your task touches.

Do **not** default-read the full README, the phase history, or the release
validation doc. Reach for them only when the task actually needs them.

## 2. Where The History Lives

- [`docs/history/webview-phases.md`](history/webview-phases.md) — the long-form
  Phase 0A → Phase 4B log (every "Implemented Scope" / "Not Implemented"
  section). Read it **only** when you need the exact data semantics or
  "not implemented" list of a specific past phase.
- [`docs/release-validation.md`](release-validation.md) — the manual release
  checklist. Read it **only** when validating a release.

Treat these as archives, not as default context.

## 3. Task Prompt Hygiene

Each task prompt / plan should state explicitly:

- **Goal files**: the exact files the task will modify.
- **Allowed reads**: the files the agent may read to do the job (prefer the
  minimal set above).
- **No broad scans**: do not grep/scan the whole repo "to understand it"
  unless the task is genuinely exploratory. Targeted `Grep` / `Glob` on a
  known directory is fine; full-tree reads are not.

## 4. When To Expand Search

Expand reading / search beyond the minimal set **only** when:

- A test fails and the cause is not in the touched files.
- A boundary or contract is unclear from `current-state.md`.
- The task explicitly references a past phase's data semantics.

Otherwise stay narrow.

## 5. Context Diet Cadence

Every 4–6 feature phases, run a **context diet** pass like Phase R1:

- Ensure `current-state.md` still matches the latest shipped phase and all
  status-bearing docs agree on the "current phase" label.
- Move any newly-accumulated per-phase prose out of README /
  `ui-webview-migration.md` and into `history/webview-phases.md`.
- Split or parametrize test files that have grown past ~1500 lines /
  accumulated duplicated static-contract assertions.
- Keep the default reading set (current-state + slim migration doc) small.

## 6. Don't Break The Boundaries

When editing docs or tests, never weaken the hard constraints in project
memory: WebView bridge may only import `worktrace.api`; no external links /
CDN / Google Fonts / `localStorage` in frontend resources; no tracebacks to
JS; `schema.sql` is the single source of DB structure; no new product
features or dependencies are introduced by a docs/tests-only phase.

## 7. Default Test Selection (Phase TG1)

Keep the "narrow read, narrow test" principle. The WorkTrace suite has grown
past 2000 cases, so do **not** default to the full `pytest` on every change.

- **Default for ordinary feature / hardening phases**: run
  `python scripts/run_affected_tests.py`. It maps the changed source / docs /
  packaging paths to a finite, conservative pytest target set, runs the
  `import worktrace.webview_main` smoke when WebView frontend resources
  change, and — when nothing changed — falls back to a light smoke set
  (startup imports, WebView bridge boundary, WebView static contracts). It
  never silently runs the full suite and introduces no new dependencies
  (pure standard library).
- **Default to the full `pytest` only** when the change is DB / schema /
  core cross-cutting (collector, resource model, path utils), or when
  validating a release / pre-push. The affected runner prints an explicit
  warning recommending full pytest for DB/schema and unknown `worktrace/`
  source changes.
- **Never** move PyInstaller or the per-user installer build into the
  affected runner; those remain manual release-validation steps.
- For a single known failure, prefer `pytest --lf` or a specific test file
  / case over the full suite.

See [`docs/release-validation.md`](release-validation.md) for the release
baseline the affected runner does **not** replace.
