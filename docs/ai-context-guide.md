# AI Context Guide

> Conventions for AI assistants (and developers) working in this repository.
> Goal: keep each iteration fast and low-token by reading only what the
> current task needs.

## 1. Default Reading Order

For any new task, default to this minimal reading order:

1. [`docs/current-state.md`](current-state.md) — the one-screen "what ships
   today" snapshot. **Start here.** It is the single source of truth for
   current shipped behavior.
2. [`docs/ui-webview-migration.md`](ui-webview-migration.md) — only the
   architecture decisions and migration principles (now slim).
3. The specific source files your task touches.

Do **not** default-read the full README, the phase history, the release
validation doc, or research docs. Reach for them only when the task actually
needs them.

## 2. Where The History Lives

- [`docs/history/webview-phases.md`](history/webview-phases.md) — the long-form
  Phase 0A → current WebView phase log (every "Implemented Scope" / "Not
  Implemented" section). Read it **only** when you need the exact data
  semantics or "not implemented" list of a specific past phase.
- [`docs/release-validation.md`](release-validation.md) — the canonical release
  baseline. Read it **only** when validating a release.

Treat these as archives, not as default context.

## 3. Documentation Governance (Phase DG1)

The repository follows a "single source of truth" documentation model so
each phase does not require editing the same facts in multiple places:

- **README** must not contain long phase implementation logs or per-phase
  chronology. It is a project overview with a short current-state pointer.
- **`docs/current-state.md`** is the **only** current shipped behavior source.
  Post-WebView migration, it no longer uses UI migration phase labels (Phase
  6F etc.) as the current-state identifier; it describes the shipped state
  directly.
- **`docs/ui-webview-migration.md`** is **architecture-only**. The WebView
  migration is closed; this document no longer carries current-status
  responsibility.
- **`docs/history/webview-phases.md`** is the archive for the Phase 0A →
  Phase 6F history. The migration is closed; ordinary maintenance should NOT
  append new UI migration phase entries.
- **`docs/release-validation.md`** is the canonical release baseline.
- Post-migration: ordinary maintenance (docs cleanup, bridge refactoring,
  test hardening) does NOT require updating the migration archive or
  creating new phase labels. Only update `docs/current-state.md` when
  shipped behavior changes.
- **`docs/release-checklist.md`** is only a compatibility pointer to
  `docs/release-validation.md`; it is retained as a stub to avoid breaking
  references.

## 4. Research Docs

- Research / scan docs live under [`docs/research/`](research/). They are
  **not default context**.
- Only read `docs/research/*` when the task explicitly concerns that research
  topic (e.g. v0.2 field encryption design).
- `docs/current-state.md` remains the single source for current shipped
  behavior; research docs describe future / unimplemented design only.

## 5. Task Prompt Hygiene

Each task prompt / plan should state explicitly:

- **Goal files**: the exact files the task will modify.
- **Allowed reads**: the files the agent may read to do the job (prefer the
  minimal set above).
- **No broad scans**: do not grep/scan the whole repo "to understand it"
  unless the task is genuinely exploratory. Targeted `Grep` / `Glob` on a
  known directory is fine; full-tree reads are not.

## 6. When To Expand Search

Expand reading / search beyond the minimal set **only** when:

- A test fails and the cause is not in the touched files.
- A boundary or contract is unclear from `current-state.md`.
- The task explicitly references a past phase's data semantics.

Otherwise stay narrow.

## 7. Context Diet Cadence

Every 4–6 feature phases, run a **context diet** pass like Phase R1 / DG1:

- Ensure `current-state.md` still matches the latest shipped behavior.
  Post-WebView migration, there is no "current phase label" to sync;
  `current-state.md` describes the shipped state directly.
- Move any newly-accumulated per-phase prose out of README /
  `ui-webview-migration.md` and into `history/webview-phases.md`. The
  migration archive is closed; do not create new phase entries for ordinary
  maintenance.
- Split or parametrize test files that have grown past ~1500 lines /
  accumulated duplicated static-contract assertions.
- Keep the default reading set (current-state + slim migration doc) small.

Phase DG1 executed this pass: README and `ui-webview-migration.md` were
slimmed, `current-state.md` was restored to a one-screen snapshot, release
docs were consolidated, and research docs were downgraded from default
context.

## 8. Don't Break The Boundaries

When editing docs or tests, never weaken the hard constraints in project
memory: WebView bridge may only import `worktrace.api`; no external links /
CDN / Google Fonts / `localStorage` in frontend resources; no tracebacks to
JS; `schema.sql` is the single source of DB structure; no new product
features or dependencies are introduced by a docs/tests-only phase.

## 9. Default Test Selection (Phase TG1)

Keep the "narrow read, narrow test" principle. WorkTrace has a large and
growing test suite, so do **not** default to the full `pytest` on every
change.

- **Default for ordinary feature / hardening phases**: run
  `python scripts/run_affected_tests.py`. It maps the changed source / docs /
  packaging paths to a finite, conservative pytest target set, runs the
  `import worktrace.webview_main` smoke when WebView frontend resources
  change, and — when nothing changed — falls back to a light smoke set
  (startup imports, WebView bridge boundary, WebView static contracts). It
  never silently runs the full suite and introduces no new dependencies
  (pure standard library). Marker shard output is diagnostic/focused
  selection guidance; concrete target selection remains the compatibility
  path while marker coverage is incremental.
- **Inventory / governance**: run `python scripts/test_inventory.py` for a
  local marker and test-structure summary, and
  `python scripts/test_inventory.py --check` for the lightweight governance
  gate. The check warns about unmarked tests but does not fail on them in
  this phase.
- **Marker-focused local feedback** can use commands such as
  `pytest -m "webview_static and contract"`,
  `pytest -m "live_display and contract"`,
  `pytest -m "collector_runtime and integration"`,
  `pytest -m "security_privacy"`, or `pytest -m "packaging"`.
- **Default to the full `pytest` only** when the change is DB / schema /
  core cross-cutting (collector, resource model, path utils), or when
  validating a release / pre-push. The affected runner prints an explicit
  warning recommending full pytest for DB/schema and unknown `worktrace/`
  source changes.
- **Never** move PyInstaller or the per-user installer build into the
  affected runner; those remain manual release-validation steps.
- **Do not introduce parallel pytest in TG1**. The `parallel_safe` and
  `serial` markers are future-planning labels only.
- For a single known failure, prefer `pytest --lf` or a specific test file
  / case over the full suite.

See [`docs/release-validation.md`](release-validation.md) for the release
baseline the affected runner does **not** replace.

## 10. Comment Hygiene Gate

After each AI coding pass, run `python scripts/comment_hygiene.py --check`.
If it fails, use `python scripts/comment_hygiene.py --json` together with
[`.ai/comment-hygiene-fixer.md`](../.ai/comment-hygiene-fixer.md) to fix it
automatically; no manual review is required. Do not add historical migration
narratives or comments that restate nearby code.
