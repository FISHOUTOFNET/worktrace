#!/usr/bin/env python3
"""Compare product benchmark results between baseline and HEAD revisions.

Reads the JSON artifacts produced by the HEAD-owned
``scripts/ci/product_benchmark_driver.py`` from baseline and HEAD result
directories, validates schema/fixture/driver consistency, computes
per-metric deltas, and enforces no-regression gates.

The driver measures three metrics via the COMMON public API
(``build_visible_snapshot``) that exists in both baseline and HEAD:

  * ``projection_20k_total_seconds`` — 20k activities projection total
  * ``projection_10k_contributions_seconds`` — 10k contributions projection total
  * ``projection_peak_memory_bytes`` — peak memory of the projection build

Gates (all must pass):
  * Each metric: HEAD median <= baseline median * (1 + tolerance/100)
  * tolerance defaults to 10% — Windows runners have ~5-10% noise.

Fail-closed contract:
  * Missing artifact, schema mismatch, fixture hash mismatch, driver
    version mismatch, Python version mismatch, or missing metric →
    exit 2 (input/schema error).
  * Sample count mismatch or zero samples → exit 3 (execution incomplete).
  * Performance gate failure → exit 4.
  * All gates pass → exit 0.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

_SCHEMA_VERSION = 1
_EXIT_OK = 0
_EXIT_INPUT_SCHEMA = 2
_EXIT_INCOMPLETE = 3
_EXIT_GATE_FAILED = 4


# ---------------------------------------------------------------------------
# Loading & validation
# ---------------------------------------------------------------------------

class ComparisonError(Exception):
    """Input/schema error (exit code 2)."""


class IncompleteError(Exception):
    """Execution incomplete error (exit code 3)."""


class GateFailure(Exception):
    """Performance gate failure (exit code 4)."""


def _load_driver_result(path: Path) -> dict[str, Any]:
    """Load and validate a single driver result JSON."""
    if not path.is_file():
        raise ComparisonError(f"required artifact missing: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ComparisonError(f"cannot parse {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ComparisonError(f"{path}: root is not an object")
    if payload.get("schema_version") != _SCHEMA_VERSION:
        raise ComparisonError(
            f"{path}: schema_version {payload.get('schema_version')} "
            f"!= expected {_SCHEMA_VERSION}"
        )
    metrics = payload.get("metrics")
    if not isinstance(metrics, dict):
        raise ComparisonError(f"{path}: metrics is not an object")
    return payload


def _validate_consistency(
    baseline: dict[str, Any],
    head: dict[str, Any],
    *,
    expected_baseline_sha: str,
    expected_head_sha: str,
) -> None:
    """Cross-check driver version, fixture hash, Python version, revision."""
    b_driver = baseline.get("driver_version", "")
    h_driver = head.get("driver_version", "")
    if b_driver != h_driver:
        raise ComparisonError(
            f"driver_version mismatch: baseline={b_driver!r} head={h_driver!r} — "
            f"baseline and HEAD must use the same driver"
        )

    b_fixture = baseline.get("fixture_hash", "")
    h_fixture = head.get("fixture_hash", "")
    if b_fixture != h_fixture:
        raise ComparisonError(
            f"fixture_hash mismatch: baseline={b_fixture!r} head={h_fixture!r} — "
            f"baseline and HEAD must use the same fixture"
        )

    # Python major.minor version must match (patch may differ).
    b_py = baseline.get("python_version", "")
    h_py = head.get("python_version", "")
    b_py_mm = ".".join(b_py.split(".")[:2]) if b_py else ""
    h_py_mm = ".".join(h_py.split(".")[:2]) if h_py else ""
    if b_py_mm != h_py_mm:
        raise ComparisonError(
            f"python_version mismatch: baseline={b_py_mm!r} head={h_py_mm!r} — "
            f"baseline and HEAD must use the same Python major.minor"
        )

    b_rev = baseline.get("revision", "")
    h_rev = head.get("revision", "")
    if b_rev != expected_baseline_sha:
        raise ComparisonError(
            f"baseline revision {b_rev!r} != expected {expected_baseline_sha!r}"
        )
    if h_rev != expected_head_sha:
        raise ComparisonError(
            f"HEAD revision {h_rev!r} != expected {expected_head_sha!r}"
        )


# ---------------------------------------------------------------------------
# Metric extraction
# ---------------------------------------------------------------------------

# (metric_key, human description, value_field, sample_field, unit)
GATED_METRICS: tuple[tuple[str, str, str, str, str], ...] = (
    (
        "projection_20k_total_seconds",
        "20k activities projection total",
        "median_seconds",
        "samples_seconds",
        "seconds",
    ),
    (
        "projection_10k_contributions_seconds",
        "10k contributions projection total",
        "median_seconds",
        "samples_seconds",
        "seconds",
    ),
    (
        "projection_peak_memory_bytes",
        "projection peak memory",
        "median_bytes",
        "samples_bytes",
        "bytes",
    ),
)


def _extract_metric(
    payload: dict[str, Any],
    metric_key: str,
    value_field: str,
    sample_field: str,
    label: str,
) -> tuple[float, list[float]]:
    """Extract (median, samples) for one metric from a driver result."""
    metrics = payload.get("metrics", {})
    entry = metrics.get(metric_key)
    if not isinstance(entry, dict):
        raise ComparisonError(f"{label}: metric {metric_key!r} missing or not object")
    if value_field not in entry:
        raise ComparisonError(
            f"{label}: metric {metric_key!r} missing {value_field!r}"
        )
    if sample_field not in entry:
        raise ComparisonError(
            f"{label}: metric {metric_key!r} missing {sample_field!r}"
        )
    samples = entry[sample_field]
    if not isinstance(samples, list):
        raise ComparisonError(
            f"{label}: metric {metric_key!r} {sample_field!r} is not a list"
        )
    if not samples:
        raise IncompleteError(
            f"{label}: metric {metric_key!r} has zero samples"
        )
    median = float(entry[value_field])
    return median, [float(s) for s in samples]


def _percent_delta(baseline: float, head: float) -> float:
    if baseline == 0:
        return 0.0 if head == 0 else 100.0
    return (head - baseline) / baseline * 100.0


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------

def _build_comparison(
    baseline_dir: Path,
    head_dir: Path,
    *,
    baseline_sha: str,
    head_sha: str,
    tolerance_pct: float,
) -> dict[str, Any]:
    baseline = _load_driver_result(baseline_dir / "product-benchmark.json")
    head = _load_driver_result(head_dir / "product-benchmark.json")

    _validate_consistency(
        baseline,
        head,
        expected_baseline_sha=baseline_sha,
        expected_head_sha=head_sha,
    )

    gated_results: list[dict[str, Any]] = []
    all_gates_passed = True

    for metric_key, description, value_field, sample_field, unit in GATED_METRICS:
        b_median, b_samples = _extract_metric(
            baseline, metric_key, value_field, sample_field, "baseline"
        )
        h_median, h_samples = _extract_metric(
            head, metric_key, value_field, sample_field, "head"
        )

        if len(b_samples) != len(h_samples):
            raise IncompleteError(
                f"{metric_key}: sample count mismatch "
                f"baseline={len(b_samples)} head={len(h_samples)}"
            )

        delta_pct = _percent_delta(b_median, h_median)
        # No-regression gate: HEAD must not exceed baseline by more than
        # tolerance_pct.  For memory, lower HEAD is an improvement.
        passed = delta_pct <= tolerance_pct
        if not passed:
            all_gates_passed = False

        gated_results.append(
            {
                "metric": metric_key,
                "description": description,
                "unit": unit,
                "baseline_median": round(b_median, 4),
                "head_median": round(h_median, 4),
                "delta": round(h_median - b_median, 4),
                "delta_pct": round(delta_pct, 1),
                "tolerance_pct": tolerance_pct,
                "baseline_samples": b_samples,
                "head_samples": h_samples,
                "baseline_min": round(min(b_samples), 4),
                "baseline_max": round(max(b_samples), 4),
                "head_min": round(min(h_samples), 4),
                "head_max": round(max(h_samples), 4),
                "gate_passed": passed,
            }
        )

    # Consistency hashes (informational — already asserted in driver).
    b_proj_hash = (
        baseline.get("metrics", {})
        .get("projection_20k_total_seconds", {})
        .get("consistency_hash", "")
    )
    h_proj_hash = (
        head.get("metrics", {})
        .get("projection_20k_total_seconds", {})
        .get("consistency_hash", "")
    )
    b_contrib_hash = (
        baseline.get("metrics", {})
        .get("projection_10k_contributions_seconds", {})
        .get("consistency_hash", "")
    )
    h_contrib_hash = (
        head.get("metrics", {})
        .get("projection_10k_contributions_seconds", {})
        .get("consistency_hash", "")
    )

    return {
        "baseline_revision": baseline_sha,
        "head_revision": head_sha,
        "baseline_target_root": baseline.get("target_root", ""),
        "head_target_root": head.get("target_root", ""),
        "driver_version": baseline.get("driver_version", ""),
        "fixture_hash": baseline.get("fixture_hash", ""),
        "baseline_python_version": baseline.get("python_version", ""),
        "head_python_version": head.get("python_version", ""),
        "tolerance_pct": tolerance_pct,
        "gated_metrics": gated_results,
        "consistency": {
            "20k_activities": {
                "baseline_hash": b_proj_hash,
                "head_hash": h_proj_hash,
                "match": b_proj_hash == h_proj_hash,
            },
            "10k_contributions": {
                "baseline_hash": b_contrib_hash,
                "head_hash": h_contrib_hash,
                "match": b_contrib_hash == h_contrib_hash,
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
    lines.append(f"- driver version: `{report['driver_version']}`")
    lines.append(f"- fixture hash: `{report['fixture_hash'][:16]}…`")
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
            f"| {row['description']} | {row['baseline_median']:.4f} | "
            f"{row['head_median']:.4f} | {row['delta']:+.4f} | "
            f"{row['delta_pct']:+.1f}% | {verdict} |"
        )
    lines.append("")

    lines.append("### Raw samples")
    lines.append("")
    for row in report["gated_metrics"]:
        lines.append(
            f"- **{row['description']}** ({row['unit']}):"
        )
        lines.append(
            f"  - baseline: {row['baseline_samples']} "
            f"(min={row['baseline_min']}, max={row['baseline_max']})"
        )
        lines.append(
            f"  - HEAD: {row['head_samples']} "
            f"(min={row['head_min']}, max={row['head_max']})"
        )
    lines.append("")

    lines.append("### Consistency hashes")
    lines.append("")
    for scenario, info in report["consistency"].items():
        match_str = "match" if info["match"] else "DIFFER"
        lines.append(
            f"- {scenario}: baseline `{info['baseline_hash'][:16]}…` vs "
            f"HEAD `{info['head_hash'][:16]}…` — {match_str}"
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
                    f"- {row['description']}: HEAD {row['head_median']:.4f} vs "
                    f"baseline {row['baseline_median']:.4f} "
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
        help="Directory containing baseline product-benchmark.json",
    )
    parser.add_argument(
        "--head-dir",
        type=Path,
        required=True,
        help="Directory containing HEAD product-benchmark.json",
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

    try:
        report = _build_comparison(
            args.baseline_dir,
            args.head_dir,
            baseline_sha=args.baseline_sha,
            head_sha=args.head_sha,
            tolerance_pct=args.tolerance_pct,
        )
    except ComparisonError as exc:
        print(f"comparison_error (input/schema): {exc}", file=sys.stderr)
        return _EXIT_INPUT_SCHEMA
    except IncompleteError as exc:
        print(f"comparison_error (incomplete): {exc}", file=sys.stderr)
        return _EXIT_INCOMPLETE

    json_text = json.dumps(report, indent=2, sort_keys=False)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json_text + "\n", encoding="utf-8")
    else:
        print(json_text)

    md_text = _build_markdown(report)
    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        with open(step_summary, "a", encoding="utf-8") as fh:
            fh.write(md_text)

    print(md_text)

    if not report["all_gates_passed"]:
        return _EXIT_GATE_FAILED
    return _EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
