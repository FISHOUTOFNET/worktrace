You are cleaning comments in the WorkTrace repository.

Inputs:
- `scripts/comment_hygiene.py --json` output
- `comment_policy.json`
- current repository state

Goal:
Make `scripts/comment_hygiene.py --check` pass without changing runtime behavior.

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
10. After changes, run:
    - `python scripts/comment_hygiene.py --check`
    - `pytest tests/test_comment_hygiene.py tests/test_run_affected_tests.py`
    - `python scripts/run_affected_tests.py`
    - `pytest`
