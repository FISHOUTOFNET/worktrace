#!/usr/bin/env python3
"""Compare product benchmark results between baseline and HEAD.

Reads JSON artifacts from ``product_benchmark_driver.py``, validates
schema/fixture/driver/revision consistency, computes per-metric deltas,
and enforces no-regression gates (HEAD median <= baseline median * 1.1)
on ``projection_20k_total_seconds``,
``projection_10k_contributions_seconds``, ``projection_peak_memory_bytes``.

Revision identity: artifacts must record matching ``requested_revision``
and ``actual_target_revision`` (``git rev-parse``); ``github_workflow_sha``
is diagnostics-only and never used for identity comparison.

Scenario isolation: each scenario's ``fixture_audit`` must report
``preexisting_activity_count == 0`` and ``inserted_count == requested_count``.

Exit codes: 0 ok; 2 input/schema (missing artifact or mismatch); 3
incomplete (sample count mismatch); 4 gate failure.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

_SCHEMA_VERSION = 2
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


def _validate_revision_identity(
    payload: dict[str, Any],
    *,
    expected_sha: str,
    label: str,
) -> None:
    """Verify the artifact's revision identity contract.

    The artifact must record both ``requested_revision`` (the value passed
    to ``--revision``) and ``actual_target_revision`` (read from
    ``git rev-parse HEAD`` on the target worktree).  The two must match
    within the artifact, and ``actual_target_revision`` must equal the
    expected SHA supplied on the CLI.  The workflow SHA is recorded
    elsewhere for diagnostics only and is never used for identity
    comparison — in pull_request workflows it can be a merge commit SHA.
    """

    requested = payload.get("requested_revision", "")
    actual = payload.get("actual_target_revision", "")
    if not requested or not actual:
        raise ComparisonError(
            f"{label}: missing requested_revision or actual_target_revision "
            f"(requested={requested!r}, actual={actual!r})"
        )
    if requested != actual:
        raise ComparisonError(
            f"{label}: requested_revision {requested!r} != "
            f"actual_target_revision {actual!r} — driver did not verify "
            f"target worktree identity"
        )
    if actual != expected_sha:
        raise ComparisonError(
            f"{label}: actual_target_revision {actual!r} != "
            f"expected {expected_sha!r}"
        )


def _validate_scenario_isolation(
    payload: dict[str, Any],
    *,
    label: str,
) -> None:
    """Verify each scenario's fixture_audit reports clean isolation.

    Each scenario's fixture_audit must report:
      * ``preexisting_activity_count == 0`` (no carryover from a prior
        scenario),
      * ``inserted_count == requested_count`` (the builder inserted every
        requested row),
      * ``connection_count >= 1`` (the O(1) connection contract held),
      * ``commit_count >= 1`` (at least one commit happened).

    The comparison fails closed on any violation so a polluted scenario
    cannot masquerade as a valid baseline/HEAD comparison.
    """

    fixture_audit = payload.get("fixture_audit")
    if not isinstance(fixture_audit, dict):
        raise ComparisonError(
            f"{label}: fixture_audit missing or not an object"
        )
    if not fixture_audit:
        raise ComparisonError(f"{label}: fixture_audit is empty")
    for scenario, audit in fixture_audit.items():
        if not isinstance(audit, dict):
            raise ComparisonError(
                f"{label}: fixture_audit[{scenario!r}] is not an object"
            )
        preexisting = audit.get("preexisting_activity_count")
        if preexisting != 0:
            raise ComparisonError(
                f"{label}: scenario {scenario!r} "
                f"preexisting_activity_count={preexisting} (expected 0) — "
                f"scenario isolation violated"
            )
        requested = audit.get("requested_count", 0)
        inserted = audit.get("inserted_count", 0)
        if inserted != requested:
            raise ComparisonError(
                f"{label}: scenario {scenario!r} inserted_count={inserted} "
                f"!= requested_count={requested}"
            )
        if audit.get("connection_count", 0) < 1:
            raise ComparisonError(
                f"{label}: scenario {scenario!r} connection_count < 1"
            )
        if audit.get("commit_count", 0) < 1:
            raise ComparisonError(
                f"{label}: scenario {scenario!r} commit_count < 1"
            )


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

    # Revision identity: verify each artifact's requested/actual revisions
    # match internally AND match the expected SHAs from the CLI.  This
    # prevents a merge-commit SHA (GITHUB_SHA) from masquerading as the
    # target revision.
    _validate_revision_identity(
        baseline, expected_sha=expected_baseline_sha, label="baseline"
    )
    _validate_revision_identity(
        head, expected_sha=expected_head_sha, label="head"
    )

    # Scenario isolation: each scenario's fixture_audit must report clean
    # isolation.  A polluted scenario invalidates the comparison.
    _validate_scenario_isolation(baseline, label="baseline")
    _validate_scenario_isolation(head, label="head")


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
        "baseline_requested_revision": baseline.get("requested_revision", ""),
        "head_requested_revision": head.get("requested_revision", ""),
        "baseline_actual_target_revision": baseline.get(
            "actual_target_revision", ""
        ),
        "head_actual_target_revision": head.get("actual_target_revision", ""),
        "baseline_github_workflow_sha": baseline.get("github_workflow_sha"),
        "head_github_workflow_sha": head.get("github_workflow_sha"),
        "baseline_target_root": baseline.get("target_root", ""),
        "head_target_root": head.get("target_root", ""),
        "driver_version": baseline.get("driver_version", ""),
        "fixture_hash": baseline.get("fixture_hash", ""),
        "baseline_python_version": baseline.get("python_version", ""),
        "head_python_version": head.get("python_version", ""),
        "tolerance_pct": tolerance_pct,
        "gated_metrics": gated_results,
        "baseline_fixture_audit": baseline.get("fixture_audit", {}),
        "head_fixture_audit": head.get("fixture_audit", {}),
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
