#!/usr/bin/env python3
"""HEAD-owned product benchmark driver.

Measures projection performance against a target revision (baseline or HEAD)
via the COMMON ``build_visible_snapshot`` API that exists in both revisions.
The driver is HEAD-owned and self-contained (own deterministic fixture builder,
no ``tests.support.*``); only ``worktrace.*`` loads from ``--target-root``.
Each revision runs in an independent process; baseline and HEAD never share one.

``build_visible_snapshot`` is used (not the HEAD-only ``get_day_projection``)
because it returns a ``ReportProjectionSnapshot`` in both revisions, delegating
to each revision's projection path for a fair same-semantics comparison.

Measured metrics
----------------
* ``projection_20k_total_seconds`` — wall-clock to build a 20,000-activity
  snapshot (sparse anchors, one paused standalone).
* ``projection_10k_contributions_seconds`` — wall-clock for 10,000
  back-to-back activities forming one large session.
* ``projection_peak_memory_bytes`` — ``tracemalloc`` peak for the 20k build.

Exit codes
----------
* 0 — success
* 2 — input/schema error (target root missing, module import failed,
       ``__file__`` not at target root)
* 3 — execution error (fixture build failed, measurement failed,
       consistency check failed)
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
import sys
import tempfile
import time
import tracemalloc
from pathlib import Path
from typing import Any

_DRIVER_VERSION = "1.0"
_SCHEMA_VERSION = 1
_EXIT_INPUT_SCHEMA = 2
_EXIT_EXECUTION = 3

# Fixed deterministic fixture parameters — no RNG, so the fixture is
# identical across revisions and runs.  The dataset shape mirrors the
# existing ``tests/support/projection_benchmark.py`` but is embedded here
# so the driver does not depend on HEAD-only test-support modules.
_REPORT_DATE = "2026-07-15"
_DAY_START_SECONDS = 9 * 3600  # 09:00:00
_SPAN_SECONDS = 13 * 3600     # 09:00:00 -> 22:00:00


# ---------------------------------------------------------------------------
# Target-root isolation
# ---------------------------------------------------------------------------

def _setup_target_path(target_root: Path) -> None:
    """Prepend ``target_root`` to ``sys.path`` so ``worktrace.*`` resolves
    to the target revision, not the HEAD workspace.
    """
    target_str = str(target_root)
    # Remove any existing entries that point at the HEAD workspace root or
    # other worktrees so only the target root is on the front.
    # Keep entries that are not the target root and not the HEAD workspace.
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
# Deterministic fixture builder (self-contained, common API only)
# ---------------------------------------------------------------------------

def _format_time(day: str, seconds_into_day: int) -> str:
    hours, rem = divmod(seconds_into_day, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{day} {hours:02d}:{minutes:02d}:{secs:02d}"


def _build_resource(index: int) -> Any:
    """Build a synthetic DetectedResource using the target revision's type."""
    from worktrace.resources.types import DetectedResource

    return DetectedResource(
        resource_kind="local_file",
        resource_subtype="document",
        display_name=f"Doc{index}",
        identity_key=f"resource:doc:{index}",
        is_anchor=(index % 17 == 0),
        confidence=80,
        source="auto",
        app_name="App",
        process_name="app.exe",
        window_title=f"Doc{index}",
        path_hint=f"D:\\Bench\\Doc{index}.txt",
        path_key=f"path:doc:{index}",
        uri_scheme="",
        uri_host="",
        uri_hint="",
        metadata_json="",
    )


def _ensure_benchmark_projects() -> dict[str, int]:
    """Create two benchmark projects if absent, returning their IDs."""
    from worktrace.services import project_service

    def _ensure(name: str) -> int:
        existing = project_service.get_project_by_name(name)
        if existing is not None:
            return int(existing["id"])
        return project_service.create_project(name)

    return {
        "anchor": _ensure("BenchAnchor"),
        "other": _ensure("BenchOther"),
    }


def _prepare_activity(
    *,
    app_name: str,
    process_name: str,
    window_title: str,
    start_time: str,
    status: str,
    source: str,
    project_id: int | None,
    resource: Any,
) -> Any:
    from worktrace.services import activity_fact_repository

    return activity_fact_repository.prepare_activity(
        start_time=start_time,
        source=source,
        payload={
            "app_name": app_name,
            "process_name": process_name,
            "window_title": window_title,
            "status": status,
            "project_id": project_id,
            "file_path_hint": None,
            "resource": resource,
        },
    )


def build_20k_dataset(activity_count: int) -> dict[str, Any]:
    """Insert ``activity_count`` synthetic facts on the fixed report date.

    Distribution mirrors ``projection_benchmark.build_benchmark_dataset``:
    continuous uncategorized normal activities, sparse manual anchors,
    short sessions interleaved with longer ones, sparse context anchors,
    and one paused standalone status row.
    """
    from worktrace.constants import SOURCE_AUTO, STATUS_NORMAL, STATUS_PAUSED
    from worktrace.db import get_connection
    from worktrace.services import activity_fact_repository
    from worktrace.services.report_fact_query_service import (
        get_uncategorized_project_id,
    )

    projects = _ensure_benchmark_projects()
    anchor_project = projects["anchor"]
    other_project = projects["other"]

    step = max(5, _SPAN_SECONDS // max(activity_count, 1))
    activity_ids: list[int] = []
    anchor_activity_ids: list[int] = []

    with get_connection() as conn:
        uncategorized_id = get_uncategorized_project_id(conn)

    for index in range(activity_count):
        start_offset = _DAY_START_SECONDS + index * step
        if start_offset >= _DAY_START_SECONDS + _SPAN_SECONDS:
            start_offset = _DAY_START_SECONDS + _SPAN_SECONDS - step
        if index % 5 == 0:
            duration = 10
        else:
            duration = max(5, step - (index % 7))
        end_offset = start_offset + duration
        start_time = _format_time(_REPORT_DATE, start_offset)
        end_time = _format_time(_REPORT_DATE, end_offset)

        status = STATUS_NORMAL
        project_id: int | None = None
        if index % 23 == 5 and index != 0:
            status = STATUS_NORMAL
            project_id = anchor_project
        elif index % 31 == 0 and index != 0:
            project_id = other_project
        elif index == max(0, activity_count - 1):
            status = STATUS_PAUSED
            project_id = None

        resource = _build_resource(index)
        prepared = _prepare_activity(
            app_name=f"App{index % 4}",
            process_name="app.exe",
            window_title=f"Doc{index}",
            start_time=start_time,
            status=status,
            source=SOURCE_AUTO,
            project_id=project_id,
            resource=resource,
        )
        with get_connection() as conn:
            activity_id = activity_fact_repository.insert_open_activity(
                conn, prepared
            )
            if status != STATUS_PAUSED:
                activity_fact_repository.close_activity(conn, activity_id, end_time)
        activity_ids.append(activity_id)
        if project_id == anchor_project:
            anchor_activity_ids.append(activity_id)

    return {
        "report_date": _REPORT_DATE,
        "activity_count": activity_count,
        "activity_ids": activity_ids,
        "anchor_project_id": anchor_project,
        "other_project_id": other_project,
        "uncategorized_project_id": uncategorized_id,
    }


def build_10k_contributions_dataset(contribution_count: int) -> dict[str, Any]:
    """Insert ``contribution_count`` back-to-back activities forming one session."""
    from worktrace.constants import SOURCE_AUTO, STATUS_NORMAL
    from worktrace.db import get_connection
    from worktrace.services import activity_fact_repository
    from worktrace.services.report_fact_query_service import (
        get_uncategorized_project_id,
    )

    projects = _ensure_benchmark_projects()
    duration = 5
    activity_ids: list[int] = []

    with get_connection() as conn:
        uncategorized_id = get_uncategorized_project_id(conn)

    for index in range(contribution_count):
        start_offset = _DAY_START_SECONDS + index * duration
        end_offset = start_offset + duration
        start_time = _format_time(_REPORT_DATE, start_offset)
        end_time = _format_time(_REPORT_DATE, end_offset)

        resource = _build_resource(index)
        prepared = _prepare_activity(
            app_name=f"App{index % 4}",
            process_name="app.exe",
            window_title=f"Doc{index}",
            start_time=start_time,
            status=STATUS_NORMAL,
            source=SOURCE_AUTO,
            project_id=None,
            resource=resource,
        )
        with get_connection() as conn:
            activity_id = activity_fact_repository.insert_open_activity(
                conn, prepared
            )
            activity_fact_repository.close_activity(conn, activity_id, end_time)
        activity_ids.append(activity_id)

    return {
        "report_date": _REPORT_DATE,
        "contribution_count": contribution_count,
        "activity_ids": activity_ids,
        "anchor_project_id": projects["anchor"],
        "other_project_id": projects["other"],
        "uncategorized_project_id": uncategorized_id,
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


def _measure_scenario(
    report_date: str,
    *,
    runs: int,
    warmup_runs: int,
    label: str,
) -> dict[str, Any]:
    """Run warmup + ``runs`` measured iterations, return samples + median."""
    # Warmup runs (not recorded).
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

    # Consistency: all runs must produce the same hash (deterministic build).
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
            statistics.median([abs(s - statistics.median(samples)) for s in samples])
            if len(samples) >= 2
            else 0.0,
            6,
        ),
        "consistency_hash": consistency_hashes[0],
        "entry_count": entry_counts[0],
        "contribution_count": contribution_counts[0],
        "session_count": session_counts[0],
    }


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


def _measure_peak_memory(report_date: str, *, runs: int, label: str) -> dict[str, Any]:
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
# Fixture hash
# ---------------------------------------------------------------------------

def _fixture_hash() -> str:
    """Compute a deterministic hash of the fixture parameters.

    The fixture is fully deterministic (no RNG), so the hash is computed
    from the fixed parameters.  Both baseline and HEAD must produce the
    same fixture hash, which the comparison layer cross-checks.
    """
    payload = json.dumps(
        {
            "report_date": _REPORT_DATE,
            "day_start_seconds": _DAY_START_SECONDS,
            "span_seconds": _SPAN_SECONDS,
            "scenarios": {
                "20k_activities": {"activity_count": 20000},
                "10k_contributions": {"contribution_count": 10000},
            },
        },
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


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
        help="Git SHA of the target revision (recorded in output for audit)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Path to write the JSON result artifact",
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=3,
        help="Number of measured iterations per scenario (default 3)",
    )
    parser.add_argument(
        "--warmup-runs",
        type=int,
        default=1,
        help="Number of warmup iterations per scenario (default 1)",
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

    # ---- Set up target-root isolation ----
    _setup_target_path(target_root)

    # ---- Verify product modules load from target root ----
    module_path = _verify_module_at_target(
        "worktrace.services.report_projection_snapshot_service", target_root
    )
    print(f"verified: report_projection_snapshot_service loaded from {module_path}")

    # ---- Isolate the database ----
    # Each revision gets a fresh temp database (never the shared user-level
    # one) so baseline and HEAD don't pollute each other's fixtures.  Schema
    # is loaded from the target revision's own schema.sql via importlib.resources.
    import worktrace.db as db

    db_tempdir = tempfile.mkdtemp(prefix="worktrace-bench-db-")
    db_path = Path(db_tempdir) / "worktrace.db"
    try:
        db.initialize_database(db_path)
        print(f"database initialized at {db_path}")

        # ---- Run scenarios ----
        started_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        # Scenario 1: 20k activities
        print("building 20k activities fixture...")
        info_proj = build_20k_dataset(20000)
        print(
            f"  inserted {info_proj['activity_count']} activities "
            f"on {info_proj['report_date']}"
        )
        metric_proj = _measure_scenario(
            info_proj["report_date"],
            runs=args.runs,
            warmup_runs=args.warmup_runs,
            label="20k_activities",
        )
        print(
            f"  20k projection median: {metric_proj['median_seconds']:.3f}s "
            f"(entries={metric_proj['entry_count']}, "
            f"contributions={metric_proj['contribution_count']}, "
            f"sessions={metric_proj['session_count']}, "
            f"hash={metric_proj['consistency_hash']})"
        )

        # Scenario 2: 10k contributions
        # The 20k scenario intentionally leaves one paused (unclosed) activity
        # to exercise the projection's paused-row path.  The single-open
        # invariant (uq_activity_log_single_open) would reject the first
        # insert_open_activity of the 10k scenario, so close any lingering
        # open activity first.  close_all_open_activities exists in both
        # baseline and HEAD, so this is a safe common-API call.
        from worktrace.db import get_connection
        from worktrace.services import activity_fact_repository
        with get_connection() as conn:
            closed_ids = activity_fact_repository.close_all_open_activities(
                conn, _format_time(_REPORT_DATE, _DAY_START_SECONDS)
            )
        if closed_ids:
            print(f"  closed {len(closed_ids)} lingering open activity before 10k scenario")

        print("building 10k contributions fixture...")
        info_contrib = build_10k_contributions_dataset(10000)
        print(
            f"  inserted {info_contrib['contribution_count']} contributions "
            f"on {info_contrib['report_date']}"
        )
        metric_contrib = _measure_scenario(
            info_contrib["report_date"],
            runs=args.runs,
            warmup_runs=args.warmup_runs,
            label="10k_contributions",
        )
        print(
            f"  10k contributions median: {metric_contrib['median_seconds']:.3f}s "
            f"(entries={metric_contrib['entry_count']}, "
            f"contributions={metric_contrib['contribution_count']}, "
            f"sessions={metric_contrib['session_count']}, "
            f"hash={metric_contrib['consistency_hash']})"
        )

        # Scenario 3: peak memory (reuses 20k fixture, fresh measurement)
        print("measuring peak memory...")
        metric_peak = _measure_peak_memory(
            info_proj["report_date"],
            runs=args.runs,
            label="peak_memory",
        )
        print(
            f"  peak memory median: {metric_peak['median_bytes']} bytes "
            f"({metric_peak['median_bytes'] / (1024 * 1024):.1f} MiB)"
        )

        finished_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        # ---- Assemble output ----
        payload: dict[str, Any] = {
            "schema_version": _SCHEMA_VERSION,
            "driver_version": _DRIVER_VERSION,
            "revision": args.revision,
            "target_root": str(target_root),
            "fixture_hash": _fixture_hash(),
            "python_version": sys.version,
            "platform": platform.platform(),
            "runner_metadata": _runner_metadata(),
            "started_at": started_at,
            "finished_at": finished_at,
            "runs": args.runs,
            "warmup_runs": args.warmup_runs,
            "metrics": {
                "projection_20k_total_seconds": metric_proj,
                "projection_10k_contributions_seconds": metric_contrib,
                "projection_peak_memory_bytes": metric_peak,
            },
        }

        _atomic_write_json(args.output, payload)
        print(f"\nresult written to {args.output}")
        return 0
    finally:
        # Clean up the isolated database so baseline and HEAD runs never
        # share fixture data.  WAL/SHM sidecar files are removed by rmtree.
        shutil.rmtree(db_tempdir, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
