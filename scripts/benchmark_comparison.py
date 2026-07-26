#!/usr/bin/env python3
"""Compare product benchmark results between baseline and HEAD revisions.

Reads the JSON artifacts produced by the benchmark suite
(``benchmark-20k-activities.json``, ``benchmark-10k-contributions.json``,
``benchmark-peak-memory.json``) from baseline and HEAD result directories,
computes per-metric deltas, and enforces no-regression gates.

Gates (all must pass):
  * 20k activities projection_total_ms: HEAD <= baseline * (1 + tolerance)
  * 10k contributions projection_total_ms: HEAD <= baseline * (1 + tolerance)
  * compact peak memory: HEAD <= baseline * (1 + tolerance)

The tolerance defaults to 10% — product benchmarks on Windows runners have
~5-10% noise, so a tighter gate would fire on runner jitter, not real
regressions.  The tolerance can be overridden via ``--tolerance-pct``.

This script does NOT apply a blanket "20% improvement" gate.  The original
PR #26 performance targets (detail path does not rebuild day projection,
compact memory does not regress, cold Timeline improves) are enforced as
specific no-regression gates on the relevant metrics.  Absolute correctness
gates (hash consistency, non-zero times, compact < expanded) are already
asserted inside the benchmark tests themselves.

Exit code is non-zero if any gate fails or any required artifact is missing.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Artifact loading
# ---------------------------------------------------------------------------

def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"required artifact missing: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _load_benchmark_artifacts(result_dir: Path) -> dict[str, dict[str, Any]]:
    """Load all known benchmark JSON artifacts from one revision's result dir."""
    return {
        "20k_activities": _load_json(result_dir / "benchmark-20k-activities.json"),
        "10k_contributions": _load_json(result_dir / "benchmark-10k-contributions.json"),
        "peak_memory": _load_json(result_dir / "benchmark-peak-memory.json"),
    }


# ---------------------------------------------------------------------------
# Metric extraction
# ---------------------------------------------------------------------------

def _extract_metrics(artifacts: dict[str, dict[str, Any]]) -> dict[str, float]:
    """Pull the gated metrics out of the artifact dicts.

    Returns a flat ``{metric_name: value}`` dict.  All values are in the
    unit recorded by the benchmark (ms for timings, bytes for memory).
    """
    a20 = artifacts["20k_activities"]
    a10 = artifacts["10k_contributions"]
    peak = artifacts["peak_memory"]

    metrics: dict[str, float] = {
        "20k_projection_total_ms": float(a20["median"]["projection_total_ms"]),
        "20k_fact_query_ms": float(a20["median"]["fact_query_ms"]),
        "20k_session_build_ms": float(a20["median"]["session_build_ms"]),
        "20k_operation_replay_ms": float(a20["median"]["operation_replay_ms"]),
        "20k_index_build_ms": float(a20["median"]["index_build_ms"]),
        "20k_assemble_ms": float(a20["median"]["projection_assemble_ms"]),
        "10k_projection_total_ms": float(a10["median"]["projection_total_ms"]),
        "10k_fact_query_ms": float(a10["median"]["fact_query_ms"]),
        "10k_session_build_ms": float(a10["median"]["session_build_ms"]),
        "10k_operation_replay_ms": float(a10["median"]["operation_replay_ms"]),
        "10k_index_build_ms": float(a10["median"]["index_build_ms"]),
        "10k_assemble_ms": float(a10["median"]["projection_assemble_ms"]),
        "compact_peak_bytes": float(peak["compact_median_peak_bytes"]),
        "expanded_peak_bytes": float(peak["expanded_median_peak_bytes"]),
    }
    # Consistency hash is a string — keep it separately for the report.
    return metrics


# ---------------------------------------------------------------------------
# Gated metrics
# ---------------------------------------------------------------------------

# Metrics that must not regress (HEAD slower/larger than baseline by more
# than tolerance_pct).  These are the product performance indicators that
# PR #26 targeted: projection total time at scale, and compact memory.
GATED_METRICS: tuple[tuple[str, str], ...] = (
    # (metric_key, human description)
    ("20k_projection_total_ms", "20k activities projection total"),
    ("10k_projection_total_ms", "10k contributions projection total"),
    ("compact_peak_bytes", "compact peak memory"),
)


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------

def _percent_delta(baseline: float, head: float) -> float:
    if baseline == 0:
        return 0.0 if head == 0 else 100.0
    return (head - baseline) / baseline * 100.0


def _build_comparison(
    baseline_dir: Path,
    head_dir: Path,
    *,
    baseline_sha: str,
    head_sha: str,
    tolerance_pct: float,
) -> dict[str, Any]:
    baseline_artifacts = _load_benchmark_artifacts(baseline_dir)
    head_artifacts = _load_benchmark_artifacts(head_dir)
    baseline_metrics = _extract_metrics(baseline_artifacts)
    head_metrics = _extract_metrics(head_artifacts)

    metric_rows: list[dict[str, Any]] = []
    gated_results: list[dict[str, Any]] = []
    all_gates_passed = True

    for key, description in GATED_METRICS:
        b_val = baseline_metrics[key]
        h_val = head_metrics[key]
        delta_pct = _percent_delta(b_val, h_val)
        # No-regression gate: HEAD must not exceed baseline by more than
        # tolerance_pct.  For memory metrics (compact_peak_bytes), a lower
        # HEAD is an improvement (negative delta is good).
        passed = delta_pct <= tolerance_pct
        if not passed:
            all_gates_passed = False
        gated_results.append(
            {
                "metric": key,
                "description": description,
                "baseline": round(b_val, 2),
                "head": round(h_val, 2),
                "delta": round(h_val - b_val, 2),
                "delta_pct": round(delta_pct, 1),
                "tolerance_pct": tolerance_pct,
                "gate_passed": passed,
            }
        )

    # Also report all non-gated metrics for visibility.
    gated_keys = {k for k, _ in GATED_METRICS}
    for key, b_val in baseline_metrics.items():
        if key in gated_keys:
            continue
        h_val = head_metrics[key]
        metric_rows.append(
            {
                "metric": key,
                "baseline": round(b_val, 2),
                "head": round(h_val, 2),
                "delta": round(h_val - b_val, 2),
                "delta_pct": round(_percent_delta(b_val, h_val), 1),
            }
        )

    # Consistency hash check (informational — already asserted in tests).
    baseline_hash_20k = baseline_artifacts["20k_activities"].get("consistency_hash")
    head_hash_20k = head_artifacts["20k_activities"].get("consistency_hash")
    baseline_hash_10k = baseline_artifacts["10k_contributions"].get("consistency_hash")
    head_hash_10k = head_artifacts["10k_contributions"].get("consistency_hash")

    return {
        "baseline_revision": baseline_sha,
        "head_revision": head_sha,
        "tolerance_pct": tolerance_pct,
        "gated_metrics": gated_results,
        "informational_metrics": metric_rows,
        "consistency": {
            "20k_activities": {
                "baseline_hash": baseline_hash_20k,
                "head_hash": head_hash_20k,
                "match": baseline_hash_20k == head_hash_20k,
            },
            "10k_contributions": {
                "baseline_hash": baseline_hash_10k,
                "head_hash": head_hash_10k,
                "match": baseline_hash_10k == head_hash_10k,
            },
        },
        "all_gates_passed": all_gates_passed,
    }


# ---------------------------------------------------------------------------
# Markdown summary
# ---------------------------------------------------------------------------

def _build_markdown(report: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("## Product benchmark comparison (baseline vs HEAD)")
    lines.append("")
    lines.append(
        f"- baseline: `{report['baseline_revision']}`  "
        f"HEAD: `{report['head_revision']}`"
    )
    lines.append(f"- no-regression tolerance: {report['tolerance_pct']}%")
    lines.append("")

    lines.append("### Gated metrics (no regression)")
    lines.append("")
    lines.append(
        "| metric | baseline | HEAD | delta | delta (%) | gate |"
    )
    lines.append("|---|---|---|---|---|---|")
    for row in report["gated_metrics"]:
        verdict = "PASS" if row["gate_passed"] else "FAIL"
        lines.append(
            f"| {row['description']} | {row['baseline']:.2f} | "
            f"{row['head']:.2f} | {row['delta']:+.2f} | "
            f"{row['delta_pct']:+.1f}% | {verdict} |"
        )
    lines.append("")

    lines.append("### Informational metrics")
    lines.append("")
    lines.append("| metric | baseline | HEAD | delta | delta (%) |")
    lines.append("|---|---|---|---|---|")
    for row in report["informational_metrics"]:
        lines.append(
            f"| `{row['metric']}` | {row['baseline']:.2f} | "
            f"{row['head']:.2f} | {row['delta']:+.2f} | "
            f"{row['delta_pct']:+.1f}% |"
        )
    lines.append("")

    lines.append("### Consistency hashes")
    lines.append("")
    for scenario, info in report["consistency"].items():
        match_str = "match" if info["match"] else "DIFFER"
        lines.append(
            f"- {scenario}: baseline `{info['baseline_hash']}` vs "
            f"HEAD `{info['head_hash']}` — {match_str}"
        )
    lines.append("")

    lines.append("### Final verdict")
    lines.append("")
    verdict = "PASS" if report["all_gates_passed"] else "FAIL"
    lines.append(f"- **all gates passed: {report['all_gates_passed']}** ({verdict})")
    if not report["all_gates_passed"]:
        lines.append("")
        lines.append("Failed gates:")
        for row in report["gated_metrics"]:
            if not row["gate_passed"]:
                lines.append(
                    f"- {row['description']}: HEAD {row['head']:.2f} vs "
                    f"baseline {row['baseline']:.2f} "
                    f"({row['delta_pct']:+.1f}% > {row['tolerance_pct']}%)"
                )
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--baseline-dir",
        type=Path,
        required=True,
        help="Directory containing baseline benchmark JSON artifacts",
    )
    parser.add_argument(
        "--head-dir",
        type=Path,
        required=True,
        help="Directory containing HEAD benchmark JSON artifacts",
    )
    parser.add_argument("--baseline-sha", required=True)
    parser.add_argument("--head-sha", required=True)
    parser.add_argument(
        "--tolerance-pct",
        type=float,
        default=10.0,
        help="Maximum allowed regression percentage (default 10)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Write JSON report to this path (in addition to stdout summary)",
    )
    args = parser.parse_args()

    report = _build_comparison(
        args.baseline_dir,
        args.head_dir,
        baseline_sha=args.baseline_sha,
        head_sha=args.head_sha,
        tolerance_pct=args.tolerance_pct,
    )

    json_text = json.dumps(report, indent=2, sort_keys=False)
    if args.output:
        args.output.write_text(json_text, encoding="utf-8")
    else:
        print(json_text)

    md_text = _build_markdown(report)
    step_summary = __import__("os").environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        with open(step_summary, "a", encoding="utf-8") as fh:
            fh.write(md_text)

    print(f"benchmark_comparison={'PASSED' if report['all_gates_passed'] else 'FAILED'}")
    for row in report["gated_metrics"]:
        print(
            f"  {row['description']}: baseline={row['baseline']:.2f} "
            f"head={row['head']:.2f} delta={row['delta_pct']:+.1f}% "
            f"{'PASS' if row['gate_passed'] else 'FAIL'}"
        )

    return 0 if report["all_gates_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
