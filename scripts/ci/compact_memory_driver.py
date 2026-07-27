#!/usr/bin/env python3
"""HEAD-owned compact-storage memory gate driver.

Measures peak memory of compact vs expanded projection storage at a single
target revision (HEAD).  HEAD-only — no baseline comparison.  Emits the
standard progress/result/failure artifact triple.

Contract: size = 5000 (override via ``--size``); 3 compact + 3 expanded
subprocesses, each a fresh ``python -u tests/support/peak_memory_probe.py``
with 120s timeout.  tracemalloc is the ONLY memory source — RSS never used.

Output contract (``--output-dir``):
* ``progress.json`` — atomic checkpoint, updated at every step transition.
  Always present after recorder creation, even on failure.
* ``result.json`` — full result payload.  Only on success.
* ``failure.json`` — only on failure (never pre-created).

Gate (all must pass): compact runs have ``duplicated_contribution_count == 0``;
expanded runs have ``duplicated_contribution_count > 0``;
``compact_median_peak_bytes < expanded_median_peak_bytes``.  NO fixed MB
threshold, NO fixed reduction-percentage gate.

Error categories: input_schema_error, revision_mismatch, compact_run_error,
expanded_run_error, result_validation_error, interrupted, unexpected_error.

Exit: 0 success; 2 input/schema; 3 execution error.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import signal
import statistics
import subprocess
import sys
import time
import traceback
from pathlib import Path
from typing import Any

_DRIVER_VERSION = "1.0"
_SCHEMA_VERSION = 3
_EXIT_INPUT_SCHEMA = 2
_EXIT_EXECUTION = 3

_DEFAULT_SIZE = 5000
_RUNS_PER_MODE = 3
_SUBPROCESS_TIMEOUT_SECONDS = 120
_MEASUREMENT_SEMANTICS = "tracemalloc peak bytes"

# Error categories returned in failure.json / progress.json.
ERROR_INPUT_SCHEMA = "input_schema_error"
ERROR_REVISION_MISMATCH = "revision_mismatch"
ERROR_COMPACT_RUN = "compact_run_error"
ERROR_EXPANDED_RUN = "expanded_run_error"
ERROR_RESULT_VALIDATION = "result_validation_error"
ERROR_INTERRUPTED = "interrupted"
ERROR_UNEXPECTED = "unexpected_error"

_EXIT_FOR_CATEGORY: dict[str, int] = {
    ERROR_INPUT_SCHEMA: _EXIT_INPUT_SCHEMA,
    ERROR_REVISION_MISMATCH: _EXIT_INPUT_SCHEMA,
    ERROR_COMPACT_RUN: _EXIT_EXECUTION,
    ERROR_EXPANDED_RUN: _EXIT_EXECUTION,
    ERROR_RESULT_VALIDATION: _EXIT_EXECUTION,
    ERROR_INTERRUPTED: _EXIT_EXECUTION,
    ERROR_UNEXPECTED: _EXIT_EXECUTION,
}


# ---------------------------------------------------------------------------
# Target-root isolation (pattern copied from product_benchmark_driver.py)
# ---------------------------------------------------------------------------

def _setup_target_path(target_root: Path) -> None:
    """Prepend ``target_root`` to ``sys.path`` so ``worktrace.*`` resolves
    to the target revision, not the HEAD workspace.
    """
    target_str = str(target_root)
    cleaned: list[str] = []
    for entry in sys.path:
        if entry == target_str:
            continue
        cleaned.append(entry)
    sys.path = [target_str] + cleaned


def _verify_module_at_target(module_name: str, target_root: Path) -> str:
    """Import ``module_name`` and verify its ``__file__`` is under target_root.

    Returns the resolved ``__file__`` path.  Raises ``SystemExit(2)`` if the
    module cannot be imported or is loaded from outside the target root —
    this prevents accidentally measuring the HEAD workspace's code when the
    target is something else.
    """
    try:
        module = __import__(module_name, fromlist=["_"])
    except Exception as exc:
        print(
            f"driver_error: cannot import {module_name} from "
            f"{target_root}: {exc}",
            file=sys.stderr,
            flush=True,
        )
        raise SystemExit(_EXIT_INPUT_SCHEMA)

    file_attr = getattr(module, "__file__", None)
    if not file_attr:
        print(
            f"driver_error: {module_name} has no __file__ attribute",
            file=sys.stderr,
            flush=True,
        )
        raise SystemExit(_EXIT_INPUT_SCHEMA)

    resolved = str(Path(file_attr).resolve())
    target_resolved = str(target_root.resolve())
    if not resolved.startswith(target_resolved + os.sep) and resolved != target_resolved:
        print(
            f"driver_error: {module_name} loaded from {resolved}, "
            f"expected under {target_resolved}",
            file=sys.stderr,
            flush=True,
        )
        raise SystemExit(_EXIT_INPUT_SCHEMA)
    return resolved


def _read_actual_target_revision(target_root: Path) -> str:
    """Return the actual HEAD sha of the target worktree.

    Runs ``git rev-parse HEAD`` inside ``target_root``.  This is the only
    value used for revision identity comparison — never ``GITHUB_SHA``,
    which can be a merge commit SHA in pull_request workflows.
    """
    try:
        output = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=str(target_root),
            text=True,
            stderr=subprocess.STDOUT,
        )
        return output.strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        print(
            f"driver_error: cannot read actual target revision from "
            f"{target_root}: {exc}",
            file=sys.stderr,
            flush=True,
        )
        raise SystemExit(_EXIT_INPUT_SCHEMA)


def _verify_revision_identity(
    requested_revision: str,
    target_root: Path,
) -> str:
    """Verify ``requested_revision`` matches the actual target worktree sha.

    Returns the actual sha on success.  Raises ``SystemExit(2)`` on mismatch
    so the gate never runs against an unverified target.
    """
    actual = _read_actual_target_revision(target_root)
    if actual != requested_revision:
        print(
            f"driver_error: requested_revision {requested_revision!r} != "
            f"actual_target_revision {actual!r} (target_root={target_root})",
            file=sys.stderr,
            flush=True,
        )
        raise SystemExit(_EXIT_INPUT_SCHEMA)
    return actual


# ---------------------------------------------------------------------------
# Atomic output helpers
# ---------------------------------------------------------------------------

def _utc_iso(epoch: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(epoch))


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    text = json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=False) + "\n"
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _runner_metadata() -> dict[str, Any]:
    on_github = os.environ.get("GITHUB_ACTIONS", "").lower() == "true"
    if not on_github:
        return {"execution_environment": "local"}
    return {
        "execution_environment": "github_actions",
        "github_sha": os.environ.get("GITHUB_SHA") or None,
        "github_run_id": os.environ.get("GITHUB_RUN_ID") or None,
        "runner_os": os.environ.get("RUNNER_OS") or None,
        "runner_arch": os.environ.get("RUNNER_ARCH") or None,
        "runner_image": os.environ.get("ImageOS") or None,
        "runner_image_version": os.environ.get("ImageVersion") or None,
    }


# ---------------------------------------------------------------------------
# ProgressRecorder (simplified, local — this is a standalone script, not a
# package, so it does NOT import from product_benchmark_driver)
# ---------------------------------------------------------------------------

class ProgressRecorder:
    """Atomic progress checkpoint writer for the compact-memory gate.

    Writes ``progress.json`` via temp-file + ``os.replace`` so a crash
    mid-write never leaves a truncated file.  Each step transition calls
    :meth:`checkpoint` with the new step and per-step bookkeeping; the
    recorder tracks ``phase_started_at`` and ``total_elapsed_seconds``
    automatically.  The recorder is the SOLE source of truth for driver
    progress; buffered stdout/stderr logs are diagnostics only.
    """

    def __init__(
        self,
        *,
        output_dir: Path,
        requested_revision: str,
        actual_target_revision: str,
        schema_version: int,
        driver_version: str,
        size: int,
        runner_metadata: dict[str, Any],
    ) -> None:
        self._output_dir = output_dir
        self._path = output_dir / "progress.json"
        self._requested_revision = requested_revision
        self._actual_target_revision = actual_target_revision
        self._schema_version = schema_version
        self._driver_version = driver_version
        self._size = size
        self._runner_metadata = runner_metadata
        self._pid = os.getpid()
        self._phase_started_at = time.time()
        self._run_started_at = self._phase_started_at
        self._phase: str = "initialized"
        self._current_mode: str | None = None
        self._current_run_index = -1
        self._completed_compact_runs = 0
        self._completed_expanded_runs = 0
        self._last_run_summary: dict[str, Any] | None = None
        self._last_payload: dict[str, Any] = self._base_payload()

    def _base_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self._schema_version,
            "driver_version": self._driver_version,
            "requested_revision": self._requested_revision,
            "actual_target_revision": self._actual_target_revision,
            "size": self._size,
            "runner_metadata": dict(self._runner_metadata),
            "pid": self._pid,
            "phase": self._phase,
            "phase_started_at": _utc_iso(self._phase_started_at),
            "updated_at": _utc_iso(time.time()),
            "phase_elapsed_seconds": 0.0,
            "total_elapsed_seconds": 0.0,
            "current_mode": self._current_mode,
            "current_run_index": self._current_run_index,
            "completed_compact_runs": self._completed_compact_runs,
            "completed_expanded_runs": self._completed_expanded_runs,
            "last_run_summary": self._last_run_summary,
        }

    def _flush(self) -> None:
        now = time.time()
        payload = self._base_payload()
        payload["phase"] = self._phase
        payload["phase_started_at"] = _utc_iso(self._phase_started_at)
        payload["updated_at"] = _utc_iso(now)
        payload["phase_elapsed_seconds"] = round(
            now - self._phase_started_at, 6
        )
        payload["total_elapsed_seconds"] = round(
            now - self._run_started_at, 6
        )
        payload["current_mode"] = self._current_mode
        payload["current_run_index"] = self._current_run_index
        payload["completed_compact_runs"] = self._completed_compact_runs
        payload["completed_expanded_runs"] = self._completed_expanded_runs
        payload["last_run_summary"] = self._last_run_summary
        self._last_payload = payload
        self._atomic_write(payload)

    def _atomic_write(self, payload: dict[str, Any]) -> None:
        self._output_dir.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        text = (
            json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=False)
            + "\n"
        )
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, self._path)

    def checkpoint(
        self,
        phase: str,
        *,
        current_mode: str | None = None,
        current_run_index: int | None = None,
        completed_compact_runs: int | None = None,
        completed_expanded_runs: int | None = None,
        last_run_summary: dict[str, Any] | None = None,
    ) -> None:
        """Atomically advance to ``phase`` and persist progress.

        Resets ``phase_started_at`` so the next ``phase_elapsed_seconds``
        measurement starts from this transition.  ``total_elapsed_seconds``
        is anchored to the recorder's creation time and never resets.
        """
        now = time.time()
        self._phase = phase
        self._phase_started_at = now
        if current_mode is not None:
            self._current_mode = current_mode
        if current_run_index is not None:
            self._current_run_index = current_run_index
        if completed_compact_runs is not None:
            self._completed_compact_runs = completed_compact_runs
        if completed_expanded_runs is not None:
            self._completed_expanded_runs = completed_expanded_runs
        if last_run_summary is not None:
            self._last_run_summary = last_run_summary
        self._flush()

    def mark_failed(
        self,
        *,
        failure_category: str,
        failure_message: str,
        failure_traceback: str | None = None,
    ) -> None:
        """Advance to the ``failed`` step and persist failure metadata."""
        now = time.time()
        self._phase = "failed"
        self._phase_started_at = now
        payload = self._last_payload
        payload["phase"] = "failed"
        payload["phase_started_at"] = _utc_iso(now)
        payload["updated_at"] = _utc_iso(now)
        payload["phase_elapsed_seconds"] = 0.0
        payload["total_elapsed_seconds"] = round(
            now - self._run_started_at, 6
        )
        payload["failure_category"] = failure_category
        payload["failure_message"] = failure_message
        if failure_traceback:
            payload["failure_traceback"] = failure_traceback
        self._last_payload = payload
        self._atomic_write(payload)

    def snapshot(self) -> dict[str, Any]:
        """Return the most recently persisted payload."""
        return dict(self._last_payload)


# ---------------------------------------------------------------------------
# Subprocess probe runner
# ---------------------------------------------------------------------------

def _run_probe(probe_path: Path, mode: str, size: int) -> dict[str, Any]:
    """Run ``peak_memory_probe.py --mode {mode} --size {size}`` in a fresh
    subprocess and return the parsed JSON result.

    Raises ``RuntimeError`` on timeout, non-zero exit, missing output, or
    invalid JSON.  The caller maps the error to ``compact_run_error`` or
    ``expanded_run_error`` based on ``mode``.
    """
    cmd: list[str] = [
        sys.executable,
        "-u",
        str(probe_path),
        "--mode",
        mode,
        "--size",
        str(size),
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=_SUBPROCESS_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"probe (mode={mode}) timed out after "
            f"{_SUBPROCESS_TIMEOUT_SECONDS}s: {exc}"
        ) from exc

    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip()
        raise RuntimeError(
            f"probe (mode={mode}) exited {proc.returncode}; stderr={stderr}"
        )

    stdout = (proc.stdout or "").strip()
    if not stdout:
        raise RuntimeError(f"probe (mode={mode}) produced no stdout output")

    lines = [line for line in stdout.splitlines() if line.strip()]
    last_line = lines[-1]
    try:
        parsed = json.loads(last_line)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"probe (mode={mode}) stdout is not valid JSON: {exc}; "
            f"stdout={stdout!r}"
        ) from exc

    if not isinstance(parsed, dict):
        raise RuntimeError(
            f"probe (mode={mode}) output is not a JSON object: {parsed!r}"
        )

    for required_key in (
        "mode",
        "size",
        "entry_count",
        "contribution_count",
        "duplicated_contribution_count",
        "current_bytes",
        "peak_bytes",
    ):
        if required_key not in parsed:
            raise RuntimeError(
                f"probe (mode={mode}) output missing key {required_key!r}: "
                f"{parsed!r}"
            )
    return parsed


# ---------------------------------------------------------------------------
# Gate validation
# ---------------------------------------------------------------------------

def _validate_gate(
    compact_runs: list[dict[str, Any]],
    expanded_runs: list[dict[str, Any]],
) -> None:
    """Assert every gate condition.  Raises ``RuntimeError`` on any failure.

    The gate is RELATIVE only: compact median peak < expanded median peak.
    There is deliberately NO fixed MB threshold and NO fixed
    reduction-percentage gate, because runner memory varies across hosts.
    """
    for run in compact_runs:
        dup = int(run["duplicated_contribution_count"])
        if dup != 0:
            raise RuntimeError(
                f"compact run {run.get('run_index')} has "
                f"duplicated_contribution_count={dup} (expected 0)"
            )

    for run in expanded_runs:
        dup = int(run["duplicated_contribution_count"])
        if dup <= 0:
            raise RuntimeError(
                f"expanded run {run.get('run_index')} has "
                f"duplicated_contribution_count={dup} (expected > 0)"
            )

    compact_peaks = [int(run["peak_bytes"]) for run in compact_runs]
    expanded_peaks = [int(run["peak_bytes"]) for run in expanded_runs]
    compact_median = statistics.median(compact_peaks)
    expanded_median = statistics.median(expanded_peaks)
    if not (compact_median < expanded_median):
        raise RuntimeError(
            f"compact median peak_bytes ({compact_median}) is not less than "
            f"expanded median peak_bytes ({expanded_median})"
        )


# ---------------------------------------------------------------------------
# Failure writer
# ---------------------------------------------------------------------------

def _write_failure(
    output_dir: Path,
    *,
    category: str,
    message: str,
    progress: dict[str, Any],
    traceback_text: str | None = None,
) -> None:
    """Write ``failure.json`` — only on failure, never pre-created."""
    payload: dict[str, Any] = {
        "failure_category": category,
        "failure_message": message,
        "phase": progress.get("phase", "unknown"),
        "progress": progress,
    }
    if traceback_text:
        payload["traceback"] = traceback_text
    _atomic_write_json(output_dir / "failure.json", payload)


# ---------------------------------------------------------------------------
# Main driver logic
# ---------------------------------------------------------------------------

def _run(
    *,
    target_root: Path,
    revision: str,
    output_dir: Path,
    size: int,
) -> int:
    """Run the compact-memory gate and write progress/result/failure."""
    probe_path = target_root / "tests" / "support" / "peak_memory_probe.py"
    if not probe_path.is_file():
        print(
            f"driver_error: probe not found at {probe_path}",
            file=sys.stderr,
            flush=True,
        )
        return _EXIT_INPUT_SCHEMA

    _setup_target_path(target_root)
    _verify_module_at_target(
        "worktrace.services.report_projection_builder", target_root
    )
    actual_revision = _verify_revision_identity(revision, target_root)

    runner_meta = _runner_metadata()
    progress = ProgressRecorder(
        output_dir=output_dir,
        requested_revision=revision,
        actual_target_revision=actual_revision,
        schema_version=_SCHEMA_VERSION,
        driver_version=_DRIVER_VERSION,
        size=size,
        runner_metadata=runner_meta,
    )
    progress.checkpoint("revision_verified")

    started_at = _utc_iso(time.time())
    failure_category = ERROR_UNEXPECTED
    failure_message = ""

    try:
        # ---- compact runs ----
        progress.checkpoint(
            "compact_started",
            current_mode="compact",
            current_run_index=-1,
            completed_compact_runs=0,
        )
        compact_runs: list[dict[str, Any]] = []
        for index in range(_RUNS_PER_MODE):
            try:
                parsed = _run_probe(probe_path, "compact", size)
            except Exception as exc:
                failure_category = ERROR_COMPACT_RUN
                failure_message = f"compact run {index} failed: {exc}"
                raise
            run_result = dict(parsed)
            run_result["run_index"] = index
            compact_runs.append(run_result)
            progress.checkpoint(
                "compact_run_completed",
                current_mode="compact",
                current_run_index=index,
                completed_compact_runs=len(compact_runs),
                last_run_summary={
                    "run_index": index,
                    "peak_bytes": run_result.get("peak_bytes"),
                    "duplicated_contribution_count": run_result.get(
                        "duplicated_contribution_count"
                    ),
                },
            )

        # ---- expanded runs ----
        progress.checkpoint(
            "expanded_started",
            current_mode="expanded",
            current_run_index=-1,
            completed_compact_runs=len(compact_runs),
            completed_expanded_runs=0,
        )
        expanded_runs: list[dict[str, Any]] = []
        for index in range(_RUNS_PER_MODE):
            try:
                parsed = _run_probe(probe_path, "expanded", size)
            except Exception as exc:
                failure_category = ERROR_EXPANDED_RUN
                failure_message = f"expanded run {index} failed: {exc}"
                raise
            run_result = dict(parsed)
            run_result["run_index"] = index
            expanded_runs.append(run_result)
            progress.checkpoint(
                "expanded_run_completed",
                current_mode="expanded",
                current_run_index=index,
                completed_expanded_runs=len(expanded_runs),
                last_run_summary={
                    "run_index": index,
                    "peak_bytes": run_result.get("peak_bytes"),
                    "duplicated_contribution_count": run_result.get(
                        "duplicated_contribution_count"
                    ),
                },
            )

        # ---- gate validation ----
        try:
            _validate_gate(compact_runs, expanded_runs)
        except Exception as exc:
            failure_category = ERROR_RESULT_VALIDATION
            failure_message = f"gate validation failed: {exc}"
            raise

        compact_peaks = [int(run["peak_bytes"]) for run in compact_runs]
        expanded_peaks = [int(run["peak_bytes"]) for run in expanded_runs]
        compact_median = statistics.median(compact_peaks)
        expanded_median = statistics.median(expanded_peaks)
        reduction_bytes = expanded_median - compact_median
        reduction_percent = (
            round((reduction_bytes / expanded_median) * 100, 6)
            if expanded_median > 0
            else 0.0
        )
        compact_duplicate_max = max(
            int(run["duplicated_contribution_count"]) for run in compact_runs
        )
        expanded_duplicate_min = min(
            int(run["duplicated_contribution_count"]) for run in expanded_runs
        )

        finished_at = _utc_iso(time.time())

        try:
            payload: dict[str, Any] = {
                "schema_version": _SCHEMA_VERSION,
                "driver_version": _DRIVER_VERSION,
                "size": size,
                "measurement_semantics": _MEASUREMENT_SEMANTICS,
                "requested_revision": revision,
                "actual_target_revision": actual_revision,
                "compact_runs": compact_runs,
                "expanded_runs": expanded_runs,
                "compact_median_peak_bytes": compact_median,
                "expanded_median_peak_bytes": expanded_median,
                "memory_reduction_bytes": reduction_bytes,
                "memory_reduction_percent": reduction_percent,
                "compact_duplicate_count": compact_duplicate_max,
                "expanded_duplicate_count": expanded_duplicate_min,
                "runner_metadata": runner_meta,
                "python_version": sys.version,
                "platform": platform.platform(),
                "started_at": started_at,
                "finished_at": finished_at,
                "gate": {
                    "compact_no_duplicates": all(
                        int(run["duplicated_contribution_count"]) == 0
                        for run in compact_runs
                    ),
                    "expanded_has_duplicates": all(
                        int(run["duplicated_contribution_count"]) > 0
                        for run in expanded_runs
                    ),
                    "compact_median_below_expanded_median": (
                        compact_median < expanded_median
                    ),
                    "uses_fixed_mb_threshold": False,
                    "uses_fixed_reduction_percent_gate": False,
                    "uses_rss": False,
                    "size": size,
                },
            }
        except Exception as exc:
            failure_category = ERROR_RESULT_VALIDATION
            failure_message = f"result payload construction failed: {exc}"
            raise

        # Write result.json BEFORE advancing progress to result_completed so
        # a crash between write and checkpoint still leaves a valid result.
        _atomic_write_json(output_dir / "result.json", payload)
        progress.checkpoint("result_completed")
        print(
            f"\ncompact-memory gate result written to "
            f"{output_dir / 'result.json'}",
            flush=True,
        )
        print(
            f"[peak memory] size={size} "
            f"compact_median_peak={compact_median} bytes "
            f"expanded_median_peak={expanded_median} bytes "
            f"reduction={reduction_bytes} bytes "
            f"({reduction_percent:.1f}%)",
            flush=True,
        )
        return 0

    except KeyboardInterrupt:
        failure_category = ERROR_INTERRUPTED
        failure_message = "interrupted by signal"
        tb = traceback.format_exc()
        progress.mark_failed(
            failure_category=failure_category,
            failure_message=failure_message,
            failure_traceback=tb,
        )
        _write_failure(
            output_dir,
            category=failure_category,
            message=failure_message,
            progress=progress.snapshot(),
            traceback_text=tb,
        )
        print(
            f"driver_error: {failure_category}: {failure_message}",
            file=sys.stderr,
            flush=True,
        )
        return _EXIT_FOR_CATEGORY.get(failure_category, _EXIT_EXECUTION)

    except Exception:
        tb = traceback.format_exc()
        progress.mark_failed(
            failure_category=failure_category,
            failure_message=failure_message,
            failure_traceback=tb,
        )
        _write_failure(
            output_dir,
            category=failure_category,
            message=failure_message,
            progress=progress.snapshot(),
            traceback_text=tb,
        )
        print(
            f"driver_error: {failure_category}: {failure_message}",
            file=sys.stderr,
            flush=True,
        )
        return _EXIT_FOR_CATEGORY.get(failure_category, _EXIT_EXECUTION)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="HEAD-owned compact-storage memory gate driver"
    )
    parser.add_argument(
        "--target-root",
        type=Path,
        required=True,
        help="Path to the target revision's worktree root",
    )
    parser.add_argument(
        "--revision",
        required=True,
        help=(
            "Git sha of the target revision (recorded in output for audit). "
            "Must match the actual HEAD of --target-root."
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Directory to write progress.json / result.json / failure.json",
    )
    parser.add_argument(
        "--size",
        type=int,
        default=_DEFAULT_SIZE,
        help=(
            f"Probe size (default {_DEFAULT_SIZE}).  The gate is defined at "
            f"size=5000; do not change without updating the contract."
        ),
    )
    args = parser.parse_args()

    target_root = args.target_root.resolve()
    if not target_root.is_dir():
        print(
            f"driver_error: --target-root does not exist or is not a directory: "
            f"{target_root}",
            file=sys.stderr,
            flush=True,
        )
        return _EXIT_INPUT_SCHEMA

    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    # Install SIGINT handler so KeyboardInterrupt produces an `interrupted`
    # failure category rather than an unclassified traceback.
    def _sigint_handler(signum, frame):
        raise KeyboardInterrupt()

    try:
        signal.signal(signal.SIGINT, _sigint_handler)
        if hasattr(signal, "SIGTERM"):
            signal.signal(signal.SIGTERM, _sigint_handler)
    except (ValueError, OSError):
        # signal can only be installed in the main thread.
        pass

    return _run(
        target_root=target_root,
        revision=args.revision,
        output_dir=output_dir,
        size=args.size,
    )


if __name__ == "__main__":
    raise SystemExit(main())
