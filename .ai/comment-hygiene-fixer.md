You are cleaning comments in the WorkTrace repository.

Inputs:
- `scripts/comment_hygiene.py --json` output
- `comment_policy.json`
- current repository state

Goal:
Make `scripts/comment_hygiene.py --check` pass without changing runtime behavior.

Current thresholds (policy version 2):
- `repo_ordinary_comment_ratio_max`: 0.08
- `file_ordinary_comment_ratio_max`: 0.12 (default per file)
- `max_contiguous_ordinary_comment_block`: 4
- `max_inline_comments_per_file`: 6
- `max_docstring_lines_default`: 18
- `max_module_docstring_lines`: 28
- `override_max_ratio`: 0.18 (hard ceiling for any per-path override)

Per-path threshold overrides:
- Defined in `comment_policy.json` under `path_threshold_overrides`.
- Each entry needs `path`, `file_ordinary_comment_ratio_max`, `reason`, and `category`.
- `category` must be one of `override_allowed_categories`.
- Exact file path match takes priority over directory prefix match (directory prefix must end with `/`).
- Glob wildcards (`*`, `?`, `[`) are rejected.
- Overrides are an exception of last resort, not a default. Clean first; override only when the remaining comments express a current enforced boundary that cannot be condensed further.

Hard rules:
1. Do not change executable behavior.
2. Delete comments that restate code.
3. Delete historical phase, migration, old behavior, temporary compatibility, and stale architecture narratives from runtime code and tests unless they express a current enforced boundary.
4. Preserve current privacy/security boundaries, non-obvious invariants, data-loss prevention constraints, transaction safety, concurrency/timing/lifecycle explanations, external API/OS/packaging caveats, and non-obvious regression-test intent.
5. Condense preserved comments to the shortest precise current-tense statement.
6. If the same explanation appears in multiple files, keep the shortest version at the owning boundary and remove duplicates.
7. Do not add broad historical explanations.
8. Do not rename stable public APIs only to remove comments.
9. Do not add dependencies.
10. Do not expand `exclude_paths` to game the ratio.
11. After changes, run:
    - `python scripts/comment_hygiene.py --check`
    - `python scripts/comment_hygiene.py --summary`
    - `pytest tests/test_comment_hygiene.py tests/test_code_comment_hygiene.py`
    - `pytest tests/test_run_affected_tests.py`
    - `python scripts/run_affected_tests.py`
    - `pytest`
