#!/usr/bin/env python3
"""HEAD-owned product benchmark driver.

Measures projection performance against a target revision (baseline or HEAD)
via the COMMON ``build_visible_snapshot`` API that exists in both revisions.
The driver is HEAD-owned and self-contained; only ``worktrace.*`` loads from
``--target-root``.  Each revision runs in an independent process; baseline
and HEAD never share one.

``build_visible_snapshot`` is used (not the HEAD-only ``get_day_projection``)
because it returns a ``ReportProjectionSnapshot`` in both revisions for a
fair same-semantics comparison.

Scenario isolation: each scenario runs in its own subprocess with its own
isolated temp database.  The controller verifies revision identity via
``git rev-parse HEAD`` on the target worktree; ``GITHUB_SHA`` is
diagnostics-only (can be a merge commit SHA in pull_request workflows).

Measured metrics: ``projection_20k_total_seconds`` (20k-activity snapshot),
``projection_10k_contributions_seconds`` (10k back-to-back activities in one
session), ``projection_peak_memory_bytes`` (``tracemalloc`` peak for 20k).

Profiles: ``--profile smoke`` (small sizes, 1 sample, infrastructure
validation, NOT a performance gate); ``--profile full`` (20000 / 10000, 3
samples, real performance gate).  The workflow only ever runs ``full``.

Exit codes: 0 success; 2 input/schema error (target root missing, module
import failed, ``__file__`` not at target root, revision mismatch); 3
execution error (fixture build / measurement / consistency / isolation).
"""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import os
import platform
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
import tracemalloc
from pathlib import Path
from typing import Any

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
    fixture_hash,
)

_DRIVER_VERSION = "2.0"
_SCHEMA_VERSION = 2
_EXIT_INPUT_SCHEMA = 2
_EXIT_EXECUTION = 3

# Profile data sizes.  Smoke is for infrastructure validation; full is for
# the real performance gate.  The workflow only ever runs full.
_PROFILES: dict[str, dict[str, Any]] = {
    "smoke": {
        "activity_count": 200,
        "contribution_count": 200,
        "runs": 1,
        "warmup_runs": 0,
    },
    "full": {
        "activity_count": 20000,
        "contribution_count": 10000,
        "runs": 3,
        "warmup_runs": 1,
    },
}


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
        )
        raise SystemExit(_EXIT_INPUT_SCHEMA)

    file_attr = getattr(module, "__file__", None)
    if not file_attr:
        print(
            f"driver_error: {module_name} has no __file__ attribute",
            file=sys.stderr,
        )
        raise SystemExit(_EXIT_INPUT_SCHEMA)

    resolved = str(Path(file_attr).resolve())
    target_resolved = str(target_root.resolve())
    if not resolved.startswith(target_resolved + os.sep) and resolved != target_resolved:
        print(
            f"driver_error: {module_name} loaded from {resolved}, "
            f"expected under {target_resolved}",
            file=sys.stderr,
        )
        raise SystemExit(_EXIT_INPUT_SCHEMA)
    return resolved


# ---------------------------------------------------------------------------
# Revision identity
# ---------------------------------------------------------------------------

def _read_actual_target_revision(target_root: Path) -> str:
    """Return the actual HEAD SHA of the target worktree.

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
        )
        raise SystemExit(_EXIT_INPUT_SCHEMA)


def _verify_revision_identity(
    requested_revision: str,
    target_root: Path,
) -> str:
    """Verify ``requested_revision`` matches the actual target worktree SHA.

    Returns the actual SHA on success.  Raises ``SystemExit(2)`` on mismatch
    so the comparison layer never sees a baseline artifact whose recorded
    revision was guessed instead of verified.
    """
    actual = _read_actual_target_revision(target_root)
    if actual != requested_revision:
        print(
            f"driver_error: requested_revision {requested_revision!r} != "
            f"actual_target_revision {actual!r} (target_root={target_root})",
            file=sys.stderr,
        )
        raise SystemExit(_EXIT_INPUT_SCHEMA)
    return actual


# ---------------------------------------------------------------------------
# Fixture hash (controller-level, covers all scenarios in the run)
# ---------------------------------------------------------------------------

def _fixture_hash(activity_count: int, contribution_count: int) -> str:
    """Compute a deterministic hash covering all scenarios in the run.

    Both baseline and HEAD must produce the same hash, which the comparison
    layer cross-checks.  The hash covers the scenario sizes, the chunk
    strategy, and the builder version so any drift invalidates the
    comparison.
    """
    activity_spec = build_20k_activity_spec(activity_count=activity_count)
    contribution_spec = build_10k_contribution_spec(
        contribution_count=contribution_count
    )
    payload = json.dumps(
        {
            "activity_spec": fixture_hash(activity_spec),
            "contribution_spec": fixture_hash(contribution_spec),
            "builder_version": _DRIVER_VERSION,
        },
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


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
        print(
            f"driver_error: {label} snapshot has {entry_count} entries; "
            f"fixture build likely failed",
            file=sys.stderr,
        )
        raise SystemExit(_EXIT_EXECUTION)


def _measure_scenario(
    report_date: str,
    *,
    runs: int,
    warmup_runs: int,
    label: str,
) -> dict[str, Any]:
    """Run warmup + ``runs`` measured iterations, return samples + median."""
    for _ in range(warmup_runs):
        snapshot = _build_snapshot_once(report_date)
        _assert_snapshot_real(snapshot, label=label)

    samples: list[float] = []
    consistency_hashes: list[str] = []
    entry_counts: list[int] = []
    contribution_counts: list[int] = []
    session_counts: list[int] = []

    for _ in range(runs):
        gc.collect()
        start = time.perf_counter()
        snapshot = _build_snapshot_once(report_date)
        elapsed = time.perf_counter() - start
        samples.append(round(elapsed, 6))
        consistency_hashes.append(getattr(snapshot, "snapshot_revision", ""))
        entry_counts.append(len(snapshot.final_entries))
        contribution_counts.append(len(snapshot.final_contributions))
        session_counts.append(len(snapshot.final_sessions))

    unique_hashes = set(consistency_hashes)
    if len(unique_hashes) != 1:
        print(
            f"driver_error: {label} snapshot hash inconsistent across runs: "
            f"{unique_hashes}",
            file=sys.stderr,
        )
        raise SystemExit(_EXIT_EXECUTION)

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
    }


def _measure_peak_memory(
    report_date: str,
    *,
    runs: int,
    label: str,
) -> dict[str, Any]:
    """Measure tracemalloc peak for building a single snapshot.

    Runs ``runs`` times and reports the median peak.  Each run starts
    tracing, builds the snapshot, captures peak, and stops tracing.
    """
    samples: list[int] = []
    for _ in range(runs):
        gc.collect()
        tracemalloc.start()
        snapshot = _build_snapshot_once(report_date)
        _current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        _assert_snapshot_real(snapshot, label=label)
        samples.append(int(peak))

    return {
        "samples_bytes": samples,
        "median_bytes": int(statistics.median(samples)),
        "min_bytes": int(min(samples)),
        "max_bytes": int(max(samples)),
        "measurement_semantics": (
            "tracemalloc peak bytes (Python allocation peak, not RSS/working set)"
        ),
    }


# ---------------------------------------------------------------------------
# Scenario subprocess
# ---------------------------------------------------------------------------

def _run_scenario_subprocess(
    *,
    scenario: str,
    target_root: Path,
    revision: str,
    output: Path,
    profile: str,
) -> None:
    """Spawn a subprocess that runs exactly one scenario and writes its result.

    The subprocess re-invokes this driver with ``--scenario`` so each
    scenario gets a fresh Python process and a fresh isolated temp DB.
    """
    cmd: list[str] = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--target-root", str(target_root),
        "--revision", revision,
        "--output", str(output),
        "--profile", profile,
        "--scenario", scenario,
    ]
    print(f"spawning scenario subprocess: {scenario}")
    result = subprocess.run(cmd)
    if result.returncode != 0:
        print(
            f"driver_error: scenario {scenario} subprocess exited with "
            f"code {result.returncode}",
            file=sys.stderr,
        )
        raise SystemExit(_EXIT_EXECUTION)


def _run_single_scenario(
    *,
    scenario: str,
    target_root: Path,
    revision: str,
    profile: str,
) -> dict[str, Any]:
    """Run one scenario in this process and return its result dict.

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
    profile_cfg = _PROFILES[profile]

    _setup_target_path(target_root)
    _verify_module_at_target(
        "worktrace.services.report_projection_snapshot_service", target_root
    )
    actual_revision = _verify_revision_identity(revision, target_root)

    import worktrace.db as db  # noqa: E402

    db_tempdir = tempfile.mkdtemp(prefix=f"worktrace-bench-{scenario}-")
    db_path = Path(db_tempdir) / "worktrace.db"
    try:
        db.initialize_database(db_path)
        print(f"[{scenario}] database initialized at {db_path}")

        started_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        if scenario == "20k_activities":
            spec = build_20k_activity_spec(
                activity_count=profile_cfg["activity_count"]
            )
            fixture_result = build_activity_fixture(spec=spec)
            report_date = fixture_result.report_date
            metric = _measure_scenario(
                report_date,
                runs=profile_cfg["runs"],
                warmup_runs=profile_cfg["warmup_runs"],
                label=scenario,
            )
            metric_key = "projection_20k_total_seconds"
        elif scenario == "10k_contributions":
            spec = build_10k_contribution_spec(
                contribution_count=profile_cfg["contribution_count"]
            )
            fixture_result = build_contribution_fixture(spec=spec)
            report_date = fixture_result.report_date
            metric = _measure_scenario(
                report_date,
                runs=profile_cfg["runs"],
                warmup_runs=profile_cfg["warmup_runs"],
                label=scenario,
            )
            metric_key = "projection_10k_contributions_seconds"
        elif scenario == "peak_memory":
            # peak_memory reuses the 20k fixture shape and measures
            # tracemalloc peak for a single snapshot build.
            spec = build_20k_activity_spec(
                activity_count=profile_cfg["activity_count"]
            )
            fixture_result = build_activity_fixture(spec=spec)
            report_date = fixture_result.report_date
            metric = _measure_peak_memory(
                report_date,
                runs=profile_cfg["runs"],
                label=scenario,
            )
            metric_key = "projection_peak_memory_bytes"
        else:
            print(
                f"driver_error: unknown scenario {scenario!r}",
                file=sys.stderr,
            )
            raise SystemExit(_EXIT_INPUT_SCHEMA)

        # Scenario isolation contracts — fail-closed on any violation so
        # the comparison layer never sees a polluted result.
        if fixture_result.preexisting_activity_count != 0:
            print(
                f"driver_error: scenario {scenario} started with "
                f"preexisting_activity_count="
                f"{fixture_result.preexisting_activity_count} (expected 0) — "
                f"scenario isolation violated",
                file=sys.stderr,
            )
            raise SystemExit(_EXIT_EXECUTION)
        if fixture_result.inserted_count != fixture_result.requested_count:
            print(
                f"driver_error: scenario {scenario} inserted "
                f"{fixture_result.inserted_count} activities but requested "
                f"{fixture_result.requested_count}",
                file=sys.stderr,
            )
            raise SystemExit(_EXIT_EXECUTION)

        print(
            f"[{scenario}] inserted {fixture_result.inserted_count} activities "
            f"in {fixture_result.fixture_build_seconds:.3f}s "
            f"(connections={fixture_result.connection_count}, "
            f"commits={fixture_result.commit_count}, "
            f"chunk_size={fixture_result.chunk_size})"
        )

        finished_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        return {
            "scenario": scenario,
            "schema_version": _SCHEMA_VERSION,
            "driver_version": _DRIVER_VERSION,
            "requested_revision": revision,
            "actual_target_revision": actual_revision,
            "github_workflow_sha": os.environ.get("GITHUB_SHA"),
            "target_root": str(target_root),
            "fixture_hash": fixture_hash(spec),
            "fixture_audit": fixture_result.to_audit_dict(),
            "python_version": sys.version,
            "platform": platform.platform(),
            "runner_metadata": _runner_metadata(),
            "started_at": started_at,
            "finished_at": finished_at,
            "profile": profile,
            "runs": profile_cfg["runs"],
            "warmup_runs": profile_cfg["warmup_runs"],
            "metrics": {
                metric_key: metric,
            },
        }
    finally:
        shutil.rmtree(db_tempdir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    text = json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=False) + "\n"
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


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
# Controller (no --scenario): spawn one subprocess per scenario and aggregate
# ---------------------------------------------------------------------------

def _run_controller(
    *,
    target_root: Path,
    revision: str,
    output: Path,
    profile: str,
) -> int:
    """Spawn one subprocess per scenario and aggregate into one artifact."""

    actual_revision = _verify_revision_identity(revision, target_root)

    profile_cfg = _PROFILES[profile]
    scenarios = ("20k_activities", "10k_contributions", "peak_memory")

    started_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    scenario_results: list[dict[str, Any]] = []
    scenario_artifact_paths: list[Path] = []

    tmp_dir = Path(tempfile.mkdtemp(prefix="worktrace-bench-controller-"))
    try:
        for scenario in scenarios:
            scenario_output = (
                tmp_dir / f"{scenario}.json"
            )
            scenario_artifact_paths.append(scenario_output)
            _run_scenario_subprocess(
                scenario=scenario,
                target_root=target_root,
                revision=revision,
                output=scenario_output,
                profile=profile,
            )
            if not scenario_output.is_file():
                print(
                    f"driver_error: scenario {scenario} did not write "
                    f"artifact at {scenario_output}",
                    file=sys.stderr,
                )
                raise SystemExit(_EXIT_EXECUTION)
            payload = json.loads(
                scenario_output.read_text(encoding="utf-8")
            )
            scenario_results.append(payload)

        finished_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        # Aggregate metrics from all scenarios into one flat metrics map.
        metrics: dict[str, Any] = {}
        for sr in scenario_results:
            metrics.update(sr.get("metrics", {}))

        # Aggregate fixture audit per scenario.
        fixture_audit: dict[str, Any] = {
            sr["scenario"]: sr.get("fixture_audit", {})
            for sr in scenario_results
            if "scenario" in sr
        }

        payload: dict[str, Any] = {
            "schema_version": _SCHEMA_VERSION,
            "driver_version": _DRIVER_VERSION,
            "requested_revision": revision,
            "actual_target_revision": actual_revision,
            "github_workflow_sha": os.environ.get("GITHUB_SHA"),
            "target_root": str(target_root),
            "fixture_hash": _fixture_hash(
                profile_cfg["activity_count"],
                profile_cfg["contribution_count"],
            ),
            "python_version": sys.version,
            "platform": platform.platform(),
            "runner_metadata": _runner_metadata(),
            "started_at": started_at,
            "finished_at": finished_at,
            "profile": profile,
            "runs": profile_cfg["runs"],
            "warmup_runs": profile_cfg["warmup_runs"],
            "scenarios": sorted(scenarios),
            "scenario_results": scenario_results,
            "fixture_audit": fixture_audit,
            "metrics": metrics,
        }

        _atomic_write_json(output, payload)
        print(f"\nresult written to {output}")
        return 0
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="HEAD-owned product benchmark driver"
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
            "Git SHA of the target revision (recorded in output for audit). "
            "Must match the actual HEAD of --target-root."
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Path to write the JSON result artifact",
    )
    parser.add_argument(
        "--profile",
        choices=("smoke", "full"),
        default="full",
        help=(
            "smoke: small data sizes for infrastructure validation. "
            "full: real data sizes for the performance gate (default)."
        ),
    )
    parser.add_argument(
        "--scenario",
        default=None,
        help=(
            "Internal: run a single scenario in this process (used by the "
            "controller subprocess spawning logic).  Leave unset for normal "
            "controller invocation."
        ),
    )
    args = parser.parse_args()

    target_root = args.target_root.resolve()
    if not target_root.is_dir():
        print(
            f"driver_error: --target-root does not exist or is not a directory: "
            f"{target_root}",
            file=sys.stderr,
        )
        return _EXIT_INPUT_SCHEMA

    if args.scenario:
        # Single-scenario mode: write directly to args.output.
        result = _run_single_scenario(
            scenario=args.scenario,
            target_root=target_root,
            revision=args.revision,
            profile=args.profile,
        )
        _atomic_write_json(args.output, result)
        print(f"\nscenario {args.scenario} result written to {args.output}")
        return 0

    return _run_controller(
        target_root=target_root,
        revision=args.revision,
        output=args.output,
        profile=args.profile,
    )


if __name__ == "__main__":
    raise SystemExit(main())
