"""Pytest plugin that selects a subset of tests from a node-ID file.

Used by ``standard-timing-validation.yml`` to run only the common test set
(shared between baseline and HEAD) or only the HEAD-only test set, without
passing thousands of node IDs on the Windows command line.

Activation:
    Set ``WORKTRACE_SELECT_FILE`` to the path of a UTF-8 text file containing
    one normalised pytest node ID per line (the format emitted by
    ``pytest --collect-only -q``). The plugin loads the file once during
    ``pytest_collection_modifyitems`` and keeps only items whose ``nodeid``
    appears in the file.

    If the environment variable is unset or empty, the plugin is a no-op and
    pytest runs its full collection — so the same plugin can stay loaded for
    the full-suite runs without affecting them.

Fail-closed contract:
    If the selection file lists a node ID that was not collected, the plugin
    reports the missing IDs and forces a non-zero exit via
    ``pytest.UsageError``. This prevents a silent "0 tests ran" pass when a
    test rename causes the selection file to drift from the worktree.

Node ID stability:
    Parametrised test IDs include their ``[param]`` suffix; the file must
    contain the full ID exactly as ``--collect-only -q`` emits it. Lines
    starting with ``#`` and blank lines are ignored.
"""

from __future__ import annotations

import os
from pathlib import Path

_SELECT_ENV = "WORKTRACE_SELECT_FILE"


def _load_selection(path: Path) -> set[str]:
    wanted: set[str] = set()
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        wanted.add(line)
    return wanted


def pytest_collection_modifyitems(session, config, items):  # noqa: D401
    """Filter collected items to those listed in the selection file."""
    raw_path = os.environ.get(_SELECT_ENV, "").strip()
    if not raw_path:
        return  # No selection requested; run everything.

    path = Path(raw_path)
    if not path.is_file():
        # Fail closed: a missing selection file is a configuration error,
        # not an implicit "run everything".
        raise _usage_error(
            f"{_SELECT_ENV} points to a missing file: {path}"
        )

    wanted = _load_selection(path)
    if not wanted:
        raise _usage_error(
            f"{_SELECT_ENV} file is empty: {path}"
        )

    selected: list = []
    seen: set[str] = set()
    for item in items:
        nid = item.nodeid
        if nid in wanted:
            selected.append(item)
            seen.add(nid)

    missing = wanted - seen
    if missing:
        # Fail closed: every requested test must be collected. A rename or
        # removal that desynchronises the selection file from the worktree
        # must surface as an explicit failure, not a silent subset run.
        sample = sorted(missing)[:5]
        raise _usage_error(
            f"{_SELECT_ENV} listed {len(missing)} test(s) not collected. "
            f"First missing: {sample}"
        )

    items[:] = selected


def _usage_error(message: str):
    """Build a pytest UsageError without importing pytest at module load.

    ``pytest`` is guaranteed to be importable inside the pytest process, but
    keeping the import deferred avoids surprising static-analysis tools when
    the module is also imported as a plain Python module by tests.
    """
    import pytest

    return pytest.UsageError(message)
