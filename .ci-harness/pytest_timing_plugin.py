"""Pytest plugin: record exact per-test timing as structured JSON.

HEAD-owned validation harness plugin.  Loaded by the Standard timing
validation workflow via ``-p pytest_timing_plugin`` after the harness
directory is prepended to ``PYTHONPATH``.  The plugin source lives in
the HEAD workspace (``.ci-harness/``) and is never read from the
worktree under test, so baseline and HEAD always share the same plugin
implementation.

What this plugin records
------------------------
For every collected test item, the plugin records the exact pytest
``report.nodeid`` (the same identifier emitted by ``--collect-only -q``)
and the ``setup`` / ``call`` / ``teardown`` durations reported by
``pytest_runtest_logreport``.  The final JSON has one entry per test:

.. code-block:: json

    {
      "nodeid": "tests/test_file.py::TestClass::test_name[param]",
      "setup_seconds": 0.01,
      "call_seconds": 0.15,
      "teardown_seconds": 0.02,
      "total_seconds": 0.18,
      "outcome": "passed"
    }

The session-level envelope records the revision, worktree root, plugin
file path, selection hash, Python/pytest versions, worker count, marker
expression, collected/selected/deselected counts, start/finish
timestamps, and the exit code.

Fail-closed contract
--------------------
* If ``--timing-json`` (or ``WORKTRACE_TIMING_JSON``) is set but the
  path is not writable, the plugin raises during ``pytest_sessionfinish``
  so the run is marked invalid instead of silently losing data.
* If the plugin is loaded but no output path is configured, the plugin
  raises during ``pytest_configure`` so a misconfigured workflow fails
  immediately instead of producing a run with no timing data.
* A test whose ``call`` phase failed (``outcome == "failed"``) is
  recorded with its real durations so the comparison layer can exclude
  failed runs from performance samples.

xdist compatibility
--------------------
If pytest-xdist is active, each worker writes a per-worker file
``<basename>-worker-<id>.json`` atomically.  The controller (non-worker
process) waits briefly for all worker files, merges them, and writes
the final ``timing.json``.  If xdist is not active, the single process
writes ``timing.json`` directly.

This plugin does NOT perform threshold judgement — that is the
responsibility of ``scripts/timing_comparison.py``.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

_TIMING_JSON_ARG = "--timing-json"
_TIMING_JSON_ENV = "WORKTRACE_TIMING_JSON"
_TIMING_REVISION_ENV = "WORKTRACE_TIMING_REVISION"
_SELECT_ENV = "WORKTRACE_SELECT_FILE"
_SCHEMA_VERSION = 1
_WORKER_PREFIX = "timing-worker-"


# ---------------------------------------------------------------------------
# Per-process state (module-global, reset in pytest_configure).
# ---------------------------------------------------------------------------

_state: dict[str, Any] = {
    "tests": {},
    "collected_count": 0,
    "selected_count": 0,
    "deselected_count": 0,
    "started_at": None,
    "finished_at": None,
    "marker_expression": "",
    "worker_count": 0,
    "output_path": None,
    "revision": "",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    """Write JSON to ``path`` atomically via temp file + replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=False) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


def _selection_hash() -> str:
    """SHA-256 of the selection file contents (empty string if no selection)."""
    raw = os.environ.get(_SELECT_ENV, "").strip()
    if not raw:
        return ""
    path = Path(raw)
    if not path.is_file():
        return ""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _worker_id(config: Any) -> str | None:
    """Return the xdist worker id ('gw0', 'gw1', ...) or None for controller/single."""
    worker = getattr(config, "workerinput", None)
    if isinstance(worker, dict) and "workerid" in worker:
        return str(worker["workerid"])
    # pytest-xdist sets config.option.numprocesses on the controller.
    return None


def _worker_count(config: Any) -> int:
    """Return the number of xdist workers (0 if xdist is not active)."""
    num = getattr(getattr(config, "option", None), "numprocesses", None)
    if not num:
        return 0
    try:
        n = int(num)
    except (TypeError, ValueError):
        return 0
    return max(0, n)


def _marker_expression(config: Any) -> str:
    expr = getattr(getattr(config, "option", None), "markexpr", None)
    return str(expr) if expr else ""


def pytest_addoption(parser: Any) -> None:
    group = parser.getgroup("worktrace-timing")
    group.addoption(
        _TIMING_JSON_ARG,
        action="store",
        default=None,
        dest="worktrace_timing_json",
        help="Path to write the structured per-test timing JSON.",
    )


def pytest_configure(config: Any) -> None:
    _state["tests"] = {}
    _state["collected_count"] = 0
    _state["selected_count"] = 0
    _state["deselected_count"] = 0
    _state["started_at"] = _now_iso()
    _state["finished_at"] = None
    _state["marker_expression"] = _marker_expression(config)
    _state["worker_count"] = _worker_count(config)

    raw_output = getattr(getattr(config, "option", None), "worktrace_timing_json", None)
    if not raw_output:
        raw_output = os.environ.get(_TIMING_JSON_ENV, "").strip()
    if not raw_output:
        raise _usage_error(
            "pytest_timing_plugin requires --timing-json=PATH or "
            f"{_TIMING_JSON_ENV} env var to be set"
        )
    _state["output_path"] = str(Path(raw_output).resolve())

    raw_revision = os.environ.get(_TIMING_REVISION_ENV, "").strip()
    if not raw_revision:
        raise _usage_error(
            f"pytest_timing_plugin requires {_TIMING_REVISION_ENV} env var "
            "to be set to the revision under test"
        )
    _state["revision"] = raw_revision


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(session: Any, config: Any, items: list[Any]) -> None:
    # tryfirst so we see the pre-deselection count before the selection
    # plugin (loaded via -p pytest_select_from_file) filters the list.
    # The selection plugin's hook does not declare tryfirst/trylast, so
    # our tryfirst hook is guaranteed to run before it.
    _state["collected_count"] = max(_state["collected_count"], len(items))


def pytest_collection_finish(session: Any) -> None:
    # session.items is now the post-deselection list (the selection
    # plugin already ran in pytest_collection_modifyitems).  Capture the
    # selected count and derive deselected_count from the pre-deselection
    # count recorded in pytest_collection_modifyitems.
    items = getattr(session, "items", None)
    selected_count = len(items) if items is not None else 0
    _state["selected_count"] = selected_count
    _state["deselected_count"] = max(0, _state["collected_count"] - selected_count)


def pytest_runtest_logreport(report: Any) -> None:
    """Record per-phase durations keyed by exact ``report.nodeid``."""
    nid = report.nodeid
    when = report.when
    if not nid or when not in ("setup", "call", "teardown"):
        return
    entry = _state["tests"].setdefault(
        nid,
        {
            "nodeid": nid,
            "setup_seconds": 0.0,
            "call_seconds": 0.0,
            "teardown_seconds": 0.0,
            "total_seconds": 0.0,
            "outcome": "skipped",
        },
    )
    duration = float(getattr(report, "duration", 0.0) or 0.0)
    if when == "setup":
        entry["setup_seconds"] = duration
    elif when == "call":
        entry["call_seconds"] = duration
    elif when == "teardown":
        entry["teardown_seconds"] = duration
    # Outcome: prefer the most decisive phase.  A failed setup or call
    # marks the whole test as failed.  A skipped setup marks it skipped.
    # Only promote to "passed" when the call phase actually passed.
    outcome = getattr(report, "outcome", "passed")
    if outcome == "failed":
        entry["outcome"] = "failed"
    elif when == "call" and outcome == "passed":
        entry["outcome"] = "passed"
    elif when == "setup" and outcome == "skipped":
        entry["outcome"] = "skipped"
    # Record xfail/xpass attributes so the comparison layer can decide
    # whether to include them in performance samples.
    # For xfail tests, pytest reports:
    #   - call outcome="skipped" + wasxfail → expected failure (xfailed)
    #   - call outcome="passed"  + wasxfail → unexpected pass (xpassed)
    #   - call outcome="failed"  + wasxfail + strict → unexpected pass, strict
    # The old code checked ``outcome == "failed"`` which never matches an
    # expected failure (pytest reports those as "skipped"), causing every
    # xfail to be misclassified as xpassed.
    if hasattr(report, "wasxfail"):
        entry["outcome"] = "xpassed" if outcome == "passed" else "xfailed"
    entry["total_seconds"] = round(
        entry["setup_seconds"] + entry["call_seconds"] + entry["teardown_seconds"],
        6,
    )
    # Round individual phases for stable storage.
    entry["setup_seconds"] = round(entry["setup_seconds"], 6)
    entry["call_seconds"] = round(entry["call_seconds"], 6)
    entry["teardown_seconds"] = round(entry["teardown_seconds"], 6)


def pytest_sessionfinish(session: Any, exitstatus: int) -> None:
    _state["finished_at"] = _now_iso()
    config = session.config
    worker = _worker_id(config)
    output_path = Path(_state["output_path"])

    if worker is not None:
        # xdist worker: write per-worker file.  The controller merges.
        worker_path = output_path.with_name(f"{_WORKER_PREFIX}{worker}.json")
        _write_session(worker_path, exitstatus, worker_id=worker)
        return

    # Controller or single-process: merge any worker files, then write
    # the final timing.json.
    merged_tests = dict(_state["tests"])
    worker_files = sorted(output_path.parent.glob(f"{_WORKER_PREFIX}*.json"))
    for wf in worker_files:
        try:
            payload = json.loads(wf.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for nid, entry in payload.get("tests", {}).items():
            if nid not in merged_tests:
                merged_tests[nid] = entry
    _state["tests"] = merged_tests
    _write_session(output_path, exitstatus, worker_id=None)

    # Clean up per-worker files after a successful merge.
    for wf in worker_files:
        try:
            wf.unlink()
        except OSError:
            pass


def _write_session(path: Path, exit_status: int, *, worker_id: str | None) -> None:
    payload = {
        "schema_version": _SCHEMA_VERSION,
        "revision": _state["revision"],
        "worktree_root": str(Path.cwd().resolve()),
        "plugin_path": str(Path(__file__).resolve()),
        "selection_hash": _selection_hash(),
        "python_version": sys.version,
        "pytest_version": pytest.__version__,
        "worker_count": _state["worker_count"],
        "worker_id": worker_id,
        "marker_expression": _state["marker_expression"],
        "selected_count": _state["selected_count"],
        "collected_count": _state["collected_count"],
        "deselected_count": _state["deselected_count"],
        "started_at": _state["started_at"],
        "finished_at": _state["finished_at"],
        "exit_code": int(exit_status),
        "tests": list(_state["tests"].values()),
    }
    _atomic_write_json(path, payload)


def _usage_error(message: str):
    return pytest.UsageError(message)
