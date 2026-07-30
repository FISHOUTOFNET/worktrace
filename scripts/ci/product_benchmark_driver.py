#!/usr/bin/env python3
"""HEAD-owned product benchmark driver — single-scenario execution.

Measures projection performance against a target revision (baseline or HEAD)
via ``build_visible_snapshot`` (exists in both revisions for fair comparison).
Each invocation runs ONE scenario with its own isolated temp database; CI uses
matrix jobs for isolation.  Revision identity verified via ``git rev-parse``;
``GITHUB_SHA`` is diagnostics-only.

Output contract (``--output-dir``):
* ``progress.json`` — atomic checkpoint, updated at every step transition.
  Always present after start, even on failure.
* ``result.json`` — full result payload.  Only on success.
* ``failure.json`` — only on failure (never pre-created).

Checkpoint fields: schema_version, driver_version, scenario, profile,
requested_revision, actual_target_revision, phase, phase_started_at,
phase_elapsed_seconds, total_elapsed_seconds, inserted_count, fixture_audit,
runner_metadata, pid.

Error categories: input_schema_error, revision_mismatch, database_init_error,
fixture_error, fixture_validation_error, warmup_error, sample_error,
result_validation_error, interrupted, unexpected_error.

Profiles: ``smoke`` (infra validation, NOT a gate); ``realistic`` (PR gate);
``full`` (stress).  Exit: 0 success; 2 input/schema; 3 execution error.
"""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import os
import platform
import shutil
import signal
import statistics
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path
from typing import Any, Callable

# Make scripts/ci importable so the subprocess can import benchmark_fixture.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_CI_DIR = Path(__file__).resolve().parent
for path in (_REPO_ROOT, _CI_DIR):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

from scripts.ci.benchmark_fixture import (  # noqa: E402
    DEFAULT_CHUNK_SIZE,
    DEFAULT_DAY_START_SECONDS,
    DEFAULT_REPORT_DATE,
    DEFAULT_SPAN_SECONDS,
    BenchmarkFixtureResult,
    BenchmarkFixtureSpec,
    build_10k_contribution_spec,
    build_20k_activity_spec,
    build_activity_fixture,
    build_contribution_fixture,
    build_realistic_heavy_day_fixture,
    build_realistic_heavy_day_spec,
    fixture_hash,
)

_DRIVER_VERSION = "3.0"
_SCHEMA_VERSION = 3
_EXIT_INPUT_SCHEMA = 2
_EXIT_EXECUTION = 3

# Scenario → metric key.  ``realistic_heavy_day`` is the PR gate;
# ``10k_contributions`` and ``20k_activities`` are stress/diagnostic only.
# The compact-memory gate has its own driver (HEAD-only, not cross-revision).
_SCENARIOS: dict[str, str] = {
    "realistic_heavy_day": "projection_realistic_heavy_day_seconds",
    "20k_activities": "projection_20k_total_seconds",
    "10k_contributions": "projection_10k_contributions_seconds",
}

# Profile data sizes.  Smoke is for infrastructure validation; full is for
# the real performance gate.  ``realistic`` is the ordinary PR gate profile.
_PROFILES: dict[str, dict[str, Any]] = {
    "smoke": {
        "activity_count": 200,
        "contribution_count": 200,
        "runs": 1,
        "warmup_runs": 0,
        "heavy_session_activity_count": 12,
    },
    "realistic": {
        "activity_count": 2000,
        "runs": 3,
        "warmup_runs": 1,
        "heavy_session_activity_count": 80,
    },
    "full": {
        "activity_count": 20000,
        "contribution_count": 10000,
        "runs": 3,
        "warmup_runs": 1,
        "heavy_session_activity_count": 0,
    },
}

# Error categories returned in failure.json / progress.json.
ERROR_INPUT_SCHEMA = "input_schema_error"
ERROR_REVISION_MISMATCH = "revision_mismatch"
ERROR_DATABASE_INIT = "database_init_error"
ERROR_FIXTURE = "fixture_error"
ERROR_FIXTURE_VALIDATION = "fixture_validation_error"
ERROR_WARMUP = "warmup_error"
ERROR_SAMPLE = "sample_error"
ERROR_RESULT_VALIDATION = "result_validation_error"
ERROR_INTERRUPTED = "interrupted"
ERROR_UNEXPECTED = "unexpected_error"


# ---------------------------------------------------------------------------
# Target-root isolation
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

    Returns the resolved ``__file__`` path.  Raises ``SystemExit`` with
    exit code 2 if the module cannot be imported or is loaded from outside
    the target root — this prevents accidentally measuring the HEAD
    workspace's code when the target is baseline.
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


# ---------------------------------------------------------------------------
# Revision identity
# ---------------------------------------------------------------------------

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
    so the comparison layer never sees a baseline artifact whose recorded
    revision was guessed instead of verified.
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
# Checkpoint writer (atomic)
# ---------------------------------------------------------------------------

class ProgressRecorder:
    """Atomic progress checkpoint writer.

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
        scenario: str,
        profile: str,
        requested_revision: str,
        actual_target_revision: str,
        schema_version: int,
        driver_version: str,
        runner_metadata: dict[str, Any],
    ) -> None:
        self._output_dir = output_dir
        self._path = output_dir / "progress.json"
        self._scenario = scenario
        self._profile = profile
        self._requested_revision = requested_revision
        self._actual_target_revision = actual_target_revision
        self._schema_version = schema_version
        self._driver_version = driver_version
        self._runner_metadata = runner_metadata
        self._pid = os.getpid()
        self._phase_started_at = time.time()
        self._run_started_at = self._phase_started_at
        self._phase: str = "initialized"
        self._inserted_count = 0
        self._requested_count = 0
        self._chunk_index = -1
        self._completed_samples = 0
        self._current_sample_index = -1
        self._fixture_audit: dict[str, Any] | None = None
        self._last_payload: dict[str, Any] = self._base_payload()

    def _base_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self._schema_version,
            "driver_version": self._driver_version,
            "scenario": self._scenario,
            "profile": self._profile,
            "requested_revision": self._requested_revision,
            "actual_target_revision": self._actual_target_revision,
            "runner_metadata": dict(self._runner_metadata),
            "pid": self._pid,
            "phase": self._phase,
            "phase_started_at": _utc_iso(self._phase_started_at),
            "updated_at": _utc_iso(time.time()),
            "phase_elapsed_seconds": 0.0,
            "total_elapsed_seconds": 0.0,
            "inserted_count": self._inserted_count,
            "requested_count": self._requested_count,
            "chunk_index": self._chunk_index,
            "completed_samples": self._completed_samples,
            "current_sample_index": self._current_sample_index,
            "fixture_audit": self._fixture_audit,
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
        payload["inserted_count"] = self._inserted_count
        payload["requested_count"] = self._requested_count
        payload["chunk_index"] = self._chunk_index
        payload["completed_samples"] = self._completed_samples
        payload["current_sample_index"] = self._current_sample_index
        payload["fixture_audit"] = self._fixture_audit
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
        inserted_count: int | None = None,
        requested_count: int | None = None,
        chunk_index: int | None = None,
        completed_samples: int | None = None,
        current_sample_index: int | None = None,
        fixture_audit: dict[str, Any] | None = None,
    ) -> None:
        """Atomically advance to ``phase`` and persist progress.

        Resets ``phase_started_at`` so the next ``phase_elapsed_seconds``
        measurement starts from this transition.  ``total_elapsed_seconds``
        is anchored to the recorder's creation time and never resets.
        """
        now = time.time()
        self._phase = phase
        self._phase_started_at = now
        if inserted_count is not None:
            self._inserted_count = inserted_count
        if requested_count is not None:
            self._requested_count = requested_count
        if chunk_index is not None:
            self._chunk_index = chunk_index
        if completed_samples is not None:
            self._completed_samples = completed_samples
        if current_sample_index is not None:
            self._current_sample_index = current_sample_index
        if fixture_audit is not None:
            self._fixture_audit = fixture_audit
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


def _utc_iso(epoch: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(epoch))


# ---------------------------------------------------------------------------
# Atomic output helpers (result.json, failure.json)
# ---------------------------------------------------------------------------

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
# Measurement
# ---------------------------------------------------------------------------

def _build_snapshot_once(report_date: str) -> Any:
    """Build a single ``ReportProjectionSnapshot`` via the common public API."""
    from worktrace.services.report_projection_snapshot_service import (
        build_visible_snapshot,
    )

    return build_visible_snapshot(report_date, report_date)


def _assert_snapshot_real(snapshot: Any, *, label: str) -> None:
    """Assert the snapshot has real data (not empty)."""
    entry_count = len(snapshot.final_entries)
    if entry_count < 1:
        raise RuntimeError(
            f"{label} snapshot has {entry_count} entries; "
            f"fixture build likely failed"
        )


def _measure_scenario(
    report_date: str,
    *,
    runs: int,
    warmup_runs: int,
    label: str,
    progress: ProgressRecorder,
) -> dict[str, Any]:
    """Run warmup + ``runs`` measured iterations, return samples + median.

    Updates ``progress`` with ``sample_started`` / ``sample_completed``
    checkpoints so partial progress is observable even when a later sample
    fails.
    """
    progress.checkpoint("warmup_started")
    for _ in range(warmup_runs):
        snapshot = _build_snapshot_once(report_date)
        _assert_snapshot_real(snapshot, label=label)
    progress.checkpoint("warmup_completed")

    samples: list[float] = []
    consistency_hashes: list[str] = []
    entry_counts: list[int] = []
    contribution_counts: list[int] = []
    session_counts: list[int] = []
    max_session_contribution_counts: list[int] = []

    for index in range(runs):
        progress.checkpoint(
            "sample_started",
            current_sample_index=index,
            completed_samples=len(samples),
        )
        gc.collect()
        start = time.perf_counter()
        snapshot = _build_snapshot_once(report_date)
        elapsed = time.perf_counter() - start
        samples.append(round(elapsed, 6))
        consistency_hashes.append(getattr(snapshot, "snapshot_revision", ""))
        entry_counts.append(len(snapshot.final_entries))
        contribution_counts.append(len(snapshot.final_contributions))
        session_counts.append(len(snapshot.final_sessions))
        # Compute the max session contribution count (event_count) across
        # all sessions.  This proves the heavy session actually formed in
        # the projection — if the heavy session has 80 activities, the max
        # event_count must be >= 80.
        max_sess_count = 0
        for sess in snapshot.final_sessions:
            ec = int(sess.get("event_count") or 0)
            if ec > max_sess_count:
                max_sess_count = ec
        max_session_contribution_counts.append(max_sess_count)
        progress.checkpoint(
            "sample_completed",
            current_sample_index=index,
            completed_samples=len(samples),
        )

    unique_hashes = set(consistency_hashes)
    if len(unique_hashes) != 1:
        raise RuntimeError(
            f"{label} snapshot hash inconsistent across runs: "
            f"{unique_hashes}"
        )

    # Verify max session contribution count is consistent across runs.
    unique_max_counts = set(max_session_contribution_counts)
    if len(unique_max_counts) != 1:
        raise RuntimeError(
            f"{label} max session contribution count inconsistent across "
            f"runs: {unique_max_counts}"
        )

    return {
        "samples_seconds": samples,
        "median_seconds": round(statistics.median(samples), 6),
        "min_seconds": round(min(samples), 6),
        "max_seconds": round(max(samples), 6),
        "mad_seconds": round(
            statistics.median(
                [abs(s - statistics.median(samples)) for s in samples]
            )
            if len(samples) >= 2
            else 0.0,
            6,
        ),
        "consistency_hash": consistency_hashes[0] if consistency_hashes else "",
        "entry_count": entry_counts[0] if entry_counts else 0,
        "contribution_count": contribution_counts[0] if contribution_counts else 0,
        "session_count": session_counts[0] if session_counts else 0,
        "actual_max_session_contribution_count": (
            max_session_contribution_counts[0]
            if max_session_contribution_counts else 0
        ),
    }


# ---------------------------------------------------------------------------
# Scenario execution
# ---------------------------------------------------------------------------

def _build_fixture_for_scenario(
    scenario: str,
    *,
    profile_cfg: dict[str, Any],
    progress: ProgressRecorder,
    chunk_callback: Callable[[int, int], None] | None = None,
) -> tuple[BenchmarkFixtureResult, str]:
    """Build the fixture for ``scenario`` and return (result, report_date).

    ``chunk_callback`` (if supplied) is invoked after every chunk commit
    so the recorder can persist ``fixture_chunk_committed`` checkpoints.
    """
    progress.checkpoint("fixture_started")

    if scenario == "realistic_heavy_day":
        spec = build_realistic_heavy_day_spec(
            activity_count=profile_cfg["activity_count"],
            heavy_session_activity_count=profile_cfg.get(
                "heavy_session_activity_count", 80
            ),
        )
        fixture_result = build_realistic_heavy_day_fixture(
            spec=spec, chunk_callback=chunk_callback,
        )
    elif scenario == "20k_activities":
        spec = build_20k_activity_spec(
            activity_count=profile_cfg["activity_count"]
        )
        fixture_result = build_activity_fixture(
            spec=spec, chunk_callback=chunk_callback,
        )
    elif scenario == "10k_contributions":
        spec = build_10k_contribution_spec(
            contribution_count=profile_cfg["contribution_count"]
        )
        fixture_result = build_contribution_fixture(
            spec=spec, chunk_callback=chunk_callback,
        )
    else:
        raise ValueError(f"unknown scenario {scenario!r}")

    progress.checkpoint(
        "fixture_completed",
        inserted_count=fixture_result.inserted_count,
        requested_count=fixture_result.requested_count,
        fixture_audit=fixture_result.to_audit_dict(),
    )
    return fixture_result, fixture_result.report_date


def _validate_fixture_audit(
    fixture_result: BenchmarkFixtureResult,
    *,
    scenario: str,
) -> None:
    """Scenario isolation contracts — fail-closed on any violation."""
    if fixture_result.preexisting_activity_count != 0:
        raise RuntimeError(
            f"scenario {scenario} started with "
            f"preexisting_activity_count="
            f"{fixture_result.preexisting_activity_count} (expected 0) — "
            f"scenario isolation violated"
        )
    if fixture_result.inserted_count != fixture_result.requested_count:
        raise RuntimeError(
            f"scenario {scenario} inserted "
            f"{fixture_result.inserted_count} activities but requested "
            f"{fixture_result.requested_count}"
        )


def _run_single_scenario(
    *,
    scenario: str,
    target_root: Path,
    revision: str,
    profile: str,
    output_dir: Path,
) -> int:
    """Run one scenario in this process and write result/failure artifacts.

    Called by ``main()`` when ``--scenario`` is set.  Each scenario:
      1. creates a fresh isolated temp database,
      2. builds only the data it needs via the shared fixture builder,
      3. asserts ``preexisting_activity_count == 0``,
      4. asserts ``requested_count == inserted_count``,
      5. runs warm-up + measured samples,
      6. writes its result and exits.

    The temp DB is removed in the ``finally`` block so baseline and HEAD
    never share fixture data even if the scenario crashes.
    """
    if scenario not in _SCENARIOS:
        print(
            f"driver_error: unknown scenario {scenario!r}; "
            f"expected one of {sorted(_SCENARIOS)}",
            file=sys.stderr,
            flush=True,
        )
        return _EXIT_INPUT_SCHEMA

    profile_cfg = _PROFILES[profile]
    metric_key = _SCENARIOS[scenario]

    _setup_target_path(target_root)
    _verify_module_at_target(
        "worktrace.services.report_projection_snapshot_service", target_root
    )
    actual_revision = _verify_revision_identity(revision, target_root)

    runner_meta = _runner_metadata()
    progress = ProgressRecorder(
        output_dir=output_dir,
        scenario=scenario,
        profile=profile,
        requested_revision=revision,
        actual_target_revision=actual_revision,
        schema_version=_SCHEMA_VERSION,
        driver_version=_DRIVER_VERSION,
        runner_metadata=runner_meta,
    )
    progress.checkpoint("revision_verified")

    import worktrace.db as db  # noqa: E402

    db_tempdir = tempfile.mkdtemp(prefix=f"worktrace-bench-{scenario}-")
    db_path = Path(db_tempdir) / "worktrace.db"
    failure_category = ERROR_UNEXPECTED
    failure_message = ""
    try:
        try:
            db.initialize_database(db_path)
            print(
                f"[{scenario}] database initialized at {db_path}",
                flush=True,
            )
            progress.checkpoint("database_initialized")
        except Exception as exc:
            failure_category = ERROR_DATABASE_INIT
            failure_message = f"database init failed: {exc}"
            raise

        # Chunk callback so the recorder can persist fixture_chunk_committed.
        def _on_chunk(chunk_index: int, inserted_so_far: int) -> None:
            progress.checkpoint(
                "fixture_chunk_committed",
                inserted_count=inserted_so_far,
                requested_count=profile_cfg[
                    "activity_count"
                    if scenario in ("20k_activities", "realistic_heavy_day")
                    else "contribution_count"
                ],
                chunk_index=chunk_index,
            )

        try:
            fixture_result, report_date = _build_fixture_for_scenario(
                scenario,
                profile_cfg=profile_cfg,
                progress=progress,
                chunk_callback=_on_chunk,
            )
        except Exception as exc:
            failure_category = ERROR_FIXTURE
            failure_message = f"fixture build failed: {exc}"
            raise

        print(
            f"[{scenario}] inserted {fixture_result.inserted_count} activities "
            f"in {fixture_result.fixture_build_seconds:.3f}s "
            f"(connections={fixture_result.connection_count}, "
            f"commits={fixture_result.commit_count}, "
            f"chunk_size={fixture_result.chunk_size})",
            flush=True,
        )

        try:
            _validate_fixture_audit(fixture_result, scenario=scenario)
        except Exception as exc:
            failure_category = ERROR_FIXTURE_VALIDATION
            failure_message = str(exc)
            raise

        try:
            metric = _measure_scenario(
                report_date,
                runs=profile_cfg["runs"],
                warmup_runs=profile_cfg["warmup_runs"],
                label=scenario,
                progress=progress,
            )
        except Exception as exc:
            failure_category = ERROR_SAMPLE if "hash inconsistent" not in str(exc) \
                else ERROR_RESULT_VALIDATION
            failure_message = f"sample measurement failed: {exc}"
            raise

        # Heavy session validation: for realistic, actual max session
        # contribution count must be >= planned heavy count.  Fail-closed
        # — if the heavy session did not form, the benchmark measures
        # the wrong workload.
        planned_heavy = fixture_result.planned_heavy_session_activity_count
        actual_max_sess = metric.get("actual_max_session_contribution_count", 0)
        if scenario == "realistic_heavy_day" and planned_heavy > 0:
            if actual_max_sess < planned_heavy:
                failure_category = ERROR_RESULT_VALIDATION
                failure_message = (
                    f"heavy session not formed: "
                    f"actual_max_session_contribution_count="
                    f"{actual_max_sess} < planned_heavy="
                    f"{planned_heavy}"
                )
                raise RuntimeError(failure_message)

        started_at = progress.snapshot().get(
            "phase_started_at") or _utc_iso(time.time())
        finished_at = _utc_iso(time.time())

        try:
            heavy_session_audit: dict[str, Any] = {
                "planned_heavy_session_activity_count": planned_heavy,
                "actual_max_session_contribution_count": actual_max_sess,
                "actual_session_count": metric.get("session_count", 0),
                "actual_entry_count": metric.get("entry_count", 0),
                "actual_contribution_count": metric.get("contribution_count", 0),
            }
            payload: dict[str, Any] = {
                "scenario": scenario,
                "schema_version": _SCHEMA_VERSION,
                "driver_version": _DRIVER_VERSION,
                "requested_revision": revision,
                "actual_target_revision": actual_revision,
                "github_workflow_sha": os.environ.get("GITHUB_SHA"),
                "target_root": str(target_root),
                "fixture_hash": fixture_hash(
                    build_realistic_heavy_day_spec(
                        activity_count=profile_cfg["activity_count"],
                        heavy_session_activity_count=profile_cfg.get(
                            "heavy_session_activity_count", 80
                        ),
                    )
                    if scenario == "realistic_heavy_day"
                    else build_20k_activity_spec(
                        activity_count=profile_cfg["activity_count"]
                    )
                    if scenario == "20k_activities"
                    else build_10k_contribution_spec(
                        contribution_count=profile_cfg["contribution_count"]
                    )
                ),
                "fixture_audit": fixture_result.to_audit_dict(),
                "heavy_session_audit": heavy_session_audit,
                "python_version": sys.version,
                "platform": platform.platform(),
                "runner_metadata": runner_meta,
                "started_at": started_at,
                "finished_at": finished_at,
                "profile": profile,
                "runs": profile_cfg["runs"],
                "warmup_runs": profile_cfg["warmup_runs"],
                "metrics": {
                    metric_key: metric,
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
            f"\nscenario {scenario} result written to {output_dir / 'result.json'}",
            flush=True,
        )
        return 0

    except KeyboardInterrupt:
        failure_category = ERROR_INTERRUPTED
        failure_message = "interrupted by signal"
        # Re-raise so the caller's exit code reflects the interrupt.
        progress.mark_failed(
            failure_category=failure_category,
            failure_message=failure_message,
        )
        _write_failure(
            output_dir,
            category=failure_category,
            message=failure_message,
            progress=progress.snapshot(),
        )
        raise
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
        return _EXIT_EXECUTION
    finally:
        shutil.rmtree(db_tempdir, ignore_errors=True)


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
# Local-only convenience wrapper (NOT used by CI)
# ---------------------------------------------------------------------------

def _run_local_wrapper(
    *,
    target_root: Path,
    revision: str,
    output_dir: Path,
    profile: str,
    scenarios: tuple[str, ...],
) -> int:
    """Run each scenario in its own subprocess and emit a thin aggregate.

    This wrapper exists for local developer convenience only.  CI never
    invokes it — CI uses matrix jobs so each scenario gets an independent
    runner, an independent artifact, and an independent timeout.  The
    wrapper does NOT own any artifact used by the comparison layer; it
    only writes a convenience ``local-wrapper-summary.json`` so a developer
    can see all scenarios in one place.
    """
    actual_revision = _verify_revision_identity(revision, target_root)
    output_dir.mkdir(parents=True, exist_ok=True)
    summaries: list[dict[str, Any]] = []
    overall_exit = 0
    for scenario in scenarios:
        scenario_dir = output_dir / scenario
        scenario_dir.mkdir(parents=True, exist_ok=True)
        cmd: list[str] = [
            sys.executable,
            "-u",
            str(Path(__file__).resolve()),
            "--target-root", str(target_root),
            "--revision", revision,
            "--output-dir", str(scenario_dir),
            "--profile", profile,
            "--scenario", scenario,
        ]
        print(f"local wrapper: spawning scenario {scenario}", flush=True)
        result = subprocess.run(cmd)
        entry: dict[str, Any] = {
            "scenario": scenario,
            "exit_code": result.returncode,
            "output_dir": str(scenario_dir),
        }
        result_path = scenario_dir / "result.json"
        if result_path.is_file():
            try:
                entry["result_present"] = True
                entry["metric_key"] = _SCENARIOS.get(scenario, "")
            except Exception:
                entry["result_present"] = False
        else:
            entry["result_present"] = False
        summaries.append(entry)
        if result.returncode != 0:
            overall_exit = result.returncode

    summary_payload = {
        "schema_version": _SCHEMA_VERSION,
        "driver_version": _DRIVER_VERSION,
        "requested_revision": revision,
        "actual_target_revision": actual_revision,
        "profile": profile,
        "scenarios": summaries,
        "note": (
            "local-only convenience wrapper.  CI does NOT use this artifact; "
            "each scenario runs as an independent matrix job with its own "
            "progress/result/failure contract."
        ),
    }
    _atomic_write_json(output_dir / "local-wrapper-summary.json", summary_payload)
    print(
        f"\nlocal wrapper summary written to "
        f"{output_dir / 'local-wrapper-summary.json'}",
        flush=True,
    )
    return overall_exit


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="HEAD-owned product benchmark driver (single scenario)"
    )
    parser.add_argument(
        "--target-root",
        type=Path,
        required=True,
        help="Path to the target revision's worktree root (baseline or HEAD)",
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
        "--profile",
        choices=("smoke", "realistic", "full"),
        default="full",
        help=(
            "smoke: small data sizes for infrastructure validation. "
            "realistic: ordinary PR gate profile (2000 activities). "
            "full: stress-level data sizes (default)."
        ),
    )
    parser.add_argument(
        "--scenario",
        choices=sorted(_SCENARIOS.keys()),
        default=None,
        help=(
            "Run a single scenario in this process.  Required for CI use; "
            "if omitted, a local-only wrapper runs both scenarios in "
            "subprocesses and emits a convenience summary."
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

    if args.scenario is None:
        # Local-only wrapper: run both scenarios in subprocesses.
        return _run_local_wrapper(
            target_root=target_root,
            revision=args.revision,
            output_dir=output_dir,
            profile=args.profile,
            scenarios=tuple(_SCENARIOS.keys()),
        )

    return _run_single_scenario(
        scenario=args.scenario,
        target_root=target_root,
        revision=args.revision,
        profile=args.profile,
        output_dir=output_dir,
    )


if __name__ == "__main__":
    raise SystemExit(main())
