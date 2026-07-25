"""Large-scale projection performance benchmarks.

These benchmarks extend the baseline 100/500/1000/2000 suite with two
large scenarios that stress the full projection chain end-to-end:

1. **20,000 activities in one day** — exercises fact query, session build,
   operation replay, freeze, index build, and assembly at scale.
2. **10,000 contributions concentrated in one session** — stresses the
   O(N) contribution index build and single-session lookup.

Both scenarios run the full projection chain via ``get_day_projection``
(not a single helper), collect timing stages from the perf scope, run
3 measured iterations (after a warmup), and report the median.  Raw
data for all three runs is written to ``test-results/`` as JSON artifacts.

A third benchmark compares compact vs expanded projection peak memory
using a subprocess ``tracemalloc`` probe, running 3 iterations per mode
and asserting compact peak < expanded peak with zero duplicate
contribution objects.

All tests are marked ``benchmark`` so they run in Performance Validation
and are excluded from Standard CI (``-m "not benchmark"``).
"""

from __future__ import annotations

import json
import statistics
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from tests.support import projection_benchmark
from worktrace.services import projection_performance
from worktrace.services.page_read_context import page_read_scope
from worktrace.services.projection_performance import projection_perf_scope
from worktrace.services.report_projection_provider import (
    clear_cache as clear_projection_cache,
    get_day_projection,
)

pytestmark = [pytest.mark.db, pytest.mark.benchmark, pytest.mark.serial]

_REPO_ROOT = Path(__file__).resolve().parents[1]
_PROBE_PATH = _REPO_ROOT / "tests" / "support" / "peak_memory_probe.py"


def _run_projection_once(report_date: str) -> dict[str, Any]:
    """Run a single cold projection build and return collected metrics."""
    projection_performance.reset_last_record()
    clear_projection_cache()
    with projection_perf_scope(report_date, surface="large_scale_benchmark"):
        with page_read_scope():
            projection = get_day_projection(report_date)
    record = projection_performance.get_last_record()
    projection_performance.reset_last_record()
    assert record is not None, "perf scope did not capture a record"

    session_count = len(projection.final_sessions)
    standalone_count = len(projection.standalone_status_entries)
    return {
        "activity_count": record.activity_count,
        "session_count": session_count,
        "standalone_status_count": standalone_count,
        "entry_count": record.entry_count,
        "contribution_count": record.contribution_count,
        "fact_query_ms": record.stage_total("fact_query"),
        "session_build_ms": record.stage_total("session_build"),
        "operation_replay_ms": record.stage_total("operation_replay"),
        "projection_materialize_ms": record.stage_total("projection_materialize"),
        "index_build_ms": record.stage_total("index_build"),
        "projection_assemble_ms": record.stage_total("projection_assemble"),
        "projection_total_ms": record.total_ms,
        "snapshot_revision": projection.snapshot_revision,
    }


def _median(values: list[float]) -> float:
    return statistics.median(values)


def _write_artifact(name: str, payload: dict[str, Any]) -> None:
    out_dir = _REPO_ROOT / "test-results"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / name
    with out_path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)
        fh.write("\n")


# --- 20,000 activities in one day ---


def test_projection_benchmark_20k_activities(temp_db):
    """20,000 activities in one day — full projection chain, 3-run median."""
    size = 20000
    projection_benchmark.build_benchmark_dataset(
        activity_count=size,
        seed_session_operation=True,
    )
    report_date = projection_benchmark.DEFAULT_REPORT_DATE

    # Warmup run (not recorded).
    _run_projection_once(report_date)

    # 3 measured runs.
    runs = [_run_projection_once(report_date) for _ in range(3)]

    summary = {
        "scenario": "20k_activities_one_day",
        "size": size,
        "run_count": 3,
        "runs": runs,
        "median": {
            "fact_query_ms": _median([r["fact_query_ms"] for r in runs]),
            "session_build_ms": _median([r["session_build_ms"] for r in runs]),
            "operation_replay_ms": _median([r["operation_replay_ms"] for r in runs]),
            "projection_materialize_ms": _median(
                [r["projection_materialize_ms"] for r in runs]
            ),
            "index_build_ms": _median([r["index_build_ms"] for r in runs]),
            "projection_assemble_ms": _median(
                [r["projection_assemble_ms"] for r in runs]
            ),
            "projection_total_ms": _median([r["projection_total_ms"] for r in runs]),
        },
        "activity_count": runs[0]["activity_count"],
        "session_count": runs[0]["session_count"],
        "entry_count": runs[0]["entry_count"],
        "contribution_count": runs[0]["contribution_count"],
        "consistency_hash": runs[0]["snapshot_revision"],
    }
    _write_artifact("benchmark-20k-activities.json", summary)

    # Consistency: all 3 runs produce the same projection hash.
    hashes = {r["snapshot_revision"] for r in runs}
    assert len(hashes) == 1, f"projection hash inconsistent across runs: {hashes}"

    # The scenario must execute real work.
    assert runs[0]["activity_count"] >= size
    assert runs[0]["entry_count"] >= 1
    assert runs[0]["contribution_count"] >= 1
    assert summary["median"]["projection_total_ms"] > 0.0

    print(
        f"\n[20k activities] "
        f"entries={summary['entry_count']} "
        f"contributions={summary['contribution_count']} "
        f"sessions={summary['session_count']} "
        f"median_total_ms={summary['median']['projection_total_ms']:.2f} "
        f"median_fact_query_ms={summary['median']['fact_query_ms']:.2f} "
        f"median_session_build_ms={summary['median']['session_build_ms']:.2f} "
        f"median_operation_replay_ms={summary['median']['operation_replay_ms']:.2f} "
        f"median_materialize_ms={summary['median']['projection_materialize_ms']:.2f} "
        f"median_index_build_ms={summary['median']['index_build_ms']:.2f} "
        f"median_assemble_ms={summary['median']['projection_assemble_ms']:.2f} "
        f"hash={summary['consistency_hash']}"
    )


# --- 10,000 contributions concentrated in one session ---


def test_projection_benchmark_10k_contributions(temp_db):
    """10,000 contributions in one session — full projection chain, 3-run median."""
    size = 10000
    projection_benchmark.build_concentrated_contributions_dataset(
        contribution_count=size,
    )
    report_date = projection_benchmark.DEFAULT_REPORT_DATE

    # Warmup run.
    _run_projection_once(report_date)

    # 3 measured runs.
    runs = [_run_projection_once(report_date) for _ in range(3)]

    summary = {
        "scenario": "10k_contributions_one_session",
        "size": size,
        "run_count": 3,
        "runs": runs,
        "median": {
            "fact_query_ms": _median([r["fact_query_ms"] for r in runs]),
            "session_build_ms": _median([r["session_build_ms"] for r in runs]),
            "operation_replay_ms": _median([r["operation_replay_ms"] for r in runs]),
            "projection_materialize_ms": _median(
                [r["projection_materialize_ms"] for r in runs]
            ),
            "index_build_ms": _median([r["index_build_ms"] for r in runs]),
            "projection_assemble_ms": _median(
                [r["projection_assemble_ms"] for r in runs]
            ),
            "projection_total_ms": _median([r["projection_total_ms"] for r in runs]),
        },
        "activity_count": runs[0]["activity_count"],
        "session_count": runs[0]["session_count"],
        "entry_count": runs[0]["entry_count"],
        "contribution_count": runs[0]["contribution_count"],
        "consistency_hash": runs[0]["snapshot_revision"],
    }
    _write_artifact("benchmark-10k-contributions.json", summary)

    # Consistency.
    hashes = {r["snapshot_revision"] for r in runs}
    assert len(hashes) == 1, f"projection hash inconsistent across runs: {hashes}"

    # The scenario must concentrate contributions in one session.
    assert runs[0]["contribution_count"] >= size
    # One session (or very few) holding all contributions.
    assert runs[0]["session_count"] >= 1
    assert runs[0]["entry_count"] >= 1
    assert summary["median"]["projection_total_ms"] > 0.0

    print(
        f"\n[10k contributions] "
        f"entries={summary['entry_count']} "
        f"contributions={summary['contribution_count']} "
        f"sessions={summary['session_count']} "
        f"median_total_ms={summary['median']['projection_total_ms']:.2f} "
        f"median_fact_query_ms={summary['median']['fact_query_ms']:.2f} "
        f"median_session_build_ms={summary['median']['session_build_ms']:.2f} "
        f"median_operation_replay_ms={summary['median']['operation_replay_ms']:.2f} "
        f"median_materialize_ms={summary['median']['projection_materialize_ms']:.2f} "
        f"median_index_build_ms={summary['median']['index_build_ms']:.2f} "
        f"median_assemble_ms={summary['median']['projection_assemble_ms']:.2f} "
        f"hash={summary['consistency_hash']}"
    )


# --- Peak memory: compact vs expanded ---


def _run_peak_memory_probe(mode: str, size: int) -> dict[str, Any]:
    """Run the peak-memory probe in a subprocess and parse its JSON output."""
    result = subprocess.run(
        [sys.executable, str(_PROBE_PATH), "--mode", mode, "--size", str(size)],
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
        timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"peak_memory_probe mode={mode} failed (exit {result.returncode}): "
            f"stderr={result.stderr}"
        )
    return json.loads(result.stdout.strip())


def test_peak_memory_compact_vs_expanded():
    """Compact projection must use less peak memory than expanded, with 0 duplicates.

    Runs the tracemalloc probe 3 times per mode in separate subprocesses,
    computes the median peak memory, and asserts:
      - compact median peak < expanded median peak
      - compact duplicated_contribution_count == 0
      - expanded duplicated_contribution_count > 0
    """
    size = 5000
    runs_per_mode = 3

    compact_runs = [
        _run_peak_memory_probe("compact", size) for _ in range(runs_per_mode)
    ]
    expanded_runs = [
        _run_peak_memory_probe("expanded", size) for _ in range(runs_per_mode)
    ]

    compact_peaks = [r["peak_bytes"] for r in compact_runs]
    expanded_peaks = [r["peak_bytes"] for r in expanded_runs]
    compact_median = _median(compact_peaks)
    expanded_median = _median(expanded_peaks)

    summary = {
        "scenario": "peak_memory_compact_vs_expanded",
        "size": size,
        "runs_per_mode": runs_per_mode,
        "compact_runs": compact_runs,
        "expanded_runs": expanded_runs,
        "compact_median_peak_bytes": compact_median,
        "expanded_median_peak_bytes": expanded_median,
        "memory_reduction_bytes": expanded_median - compact_median,
        "memory_reduction_percent": (
            (expanded_median - compact_median) / expanded_median * 100.0
            if expanded_median > 0
            else 0.0
        ),
        "measurement_semantics": (
            "tracemalloc peak bytes (Python allocation peak, not RSS/working set)"
        ),
    }
    _write_artifact("benchmark-peak-memory.json", summary)

    # Compact has zero duplicate contribution objects.
    for run in compact_runs:
        assert run["duplicated_contribution_count"] == 0, (
            f"compact mode must have 0 duplicate contributions, "
            f"got {run['duplicated_contribution_count']}"
        )

    # Expanded has duplicates (proving the reference model is meaningful).
    for run in expanded_runs:
        assert run["duplicated_contribution_count"] > 0, (
            f"expanded mode must have >0 duplicate contributions, "
            f"got {run['duplicated_contribution_count']}"
        )

    # Compact median peak < expanded median peak (relative comparison,
    # not an absolute MB threshold — runner memory varies).
    assert compact_median < expanded_median, (
        f"compact median peak ({compact_median} bytes) must be less than "
        f"expanded median peak ({expanded_median} bytes)"
    )

    print(
        f"\n[peak memory] "
        f"size={size} "
        f"compact_median_peak={compact_median} bytes "
        f"expanded_median_peak={expanded_median} bytes "
        f"reduction={summary['memory_reduction_bytes']} bytes "
        f"({summary['memory_reduction_percent']:.1f}%)"
    )
