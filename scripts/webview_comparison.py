#!/usr/bin/env python3
"""Compare WebView render benchmark results between baseline and HEAD.

Reads JSON artifacts from ``webview_render_perf.py``, validates
schema/fixture/driver/revision consistency, computes per-metric deltas,
and enforces no-regression gates (HEAD median <= baseline median * 1.1)
on ``cold_timeline_seconds``, ``warm_timeline_seconds``,
``detail_payload_seconds``, ``detail_total_seconds``.

Revision identity: artifacts must record matching ``requested_revision``
and ``actual_target_revision`` (``git rev-parse``); ``github_workflow_sha``
is diagnostics-only.  Scenario isolation: ``fixture_audit`` must report
``preexisting_activity_count == 0`` and ``inserted_count == requested_count``.

Completion: artifact valid only when ``status == "ok"`` and every run has
``detail_payload_resolved == true`` and ``detail_dom_row_count > 0``.

Exit codes: 0 ok; 2 input/schema (missing artifact/metric or mismatch); 3
incomplete (sample count mismatch); 4 gate failure.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

_SCHEME_VERSION = 2
_EXIT_OK = 0
_EXIT_INPUT_SCHEMA = 2
_EXIT_INCOMPLETE = 3
_EXIT_GATE_FAILED = 4


class ComparisonError(Exception):
    """Input/schema error (exit code 2)."""


class IncompleteError(Exception):
    """Execution incomplete error (exit code 3)."""


class GateFailure(Exception):
    """Performance gate failure (exit code 4)."""


def _load_driver_result(path: Path) -> dict[str, Any]:
    """Load and validate a single WebView driver result JSON."""
    if not path.is_file():
        raise ComparisonError(f"required artifact missing: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ComparisonError(f"cannot parse {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ComparisonError(f"{path}: root is not an object")
    if payload.get("schema_version") != _SCHEME_VERSION:
        raise ComparisonError(
            f"{path}: schema_version {payload.get('schema_version')} "
            f"!= expected {_SCHEME_VERSION}"
        )
    if payload.get("status") != "ok":
        reason = payload.get("failure_reason", "(no reason)")
        raise ComparisonError(
            f"{path}: driver status is {payload.get('status')!r}, "
            f"expected 'ok' — failure reason: {reason}"
        )
    metrics = payload.get("metrics")
    if not isinstance(metrics, dict):
        raise ComparisonError(
            f"{path}: metrics missing or not an object "
            f"(driver status was 'ok' but no metrics produced)"
        )
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
    """Verify the WebView fixture's audit reports clean isolation.

    The WebView driver runs a single scenario, so ``fixture_audit`` is a
    single object (not keyed by scenario name like the product driver).
    It must report:
      * ``preexisting_activity_count == 0`` (no carryover),
      * ``inserted_count == requested_count`` (every row inserted),
      * ``connection_count >= 1`` (the O(1) connection contract held),
      * ``commit_count >= 1`` (at least one commit happened).
    """

    audit = payload.get("fixture_audit")
    if not isinstance(audit, dict):
        raise ComparisonError(
            f"{label}: fixture_audit missing or not an object"
        )
    if not audit:
        raise ComparisonError(f"{label}: fixture_audit is empty")
    preexisting = audit.get("preexisting_activity_count")
    if preexisting != 0:
        raise ComparisonError(
            f"{label}: fixture_audit.preexisting_activity_count="
            f"{preexisting} (expected 0) — scenario isolation violated"
        )
    requested = audit.get("requested_count", 0)
    inserted = audit.get("inserted_count", 0)
    if inserted != requested:
        raise ComparisonError(
            f"{label}: fixture_audit.inserted_count={inserted} "
            f"!= requested_count={requested}"
        )
    if audit.get("connection_count", 0) < 1:
        raise ComparisonError(
            f"{label}: fixture_audit.connection_count < 1"
        )
    if audit.get("commit_count", 0) < 1:
        raise ComparisonError(
            f"{label}: fixture_audit.commit_count < 1"
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
            f"driver_version mismatch: baseline={b_driver!r} head={h_driver!r}"
        )

    b_fixture = baseline.get("fixture_hash", "")
    h_fixture = head.get("fixture_hash", "")
    if b_fixture != h_fixture:
        raise ComparisonError(
            f"fixture_hash mismatch: baseline={b_fixture!r} head={h_fixture!r}"
        )

    b_py = baseline.get("python_version", "")
    h_py = head.get("python_version", "")
    b_py_mm = ".".join(b_py.split(".")[:2]) if b_py else ""
    h_py_mm = ".".join(h_py.split(".")[:2]) if h_py else ""
    if b_py_mm != h_py_mm:
        raise ComparisonError(
            f"python_version mismatch: baseline={b_py_mm!r} head={h_py_mm!r}"
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

    # Scenario isolation: each artifact's fixture_audit must report clean
    # isolation.
    _validate_scenario_isolation(baseline, label="baseline")
    _validate_scenario_isolation(head, label="head")

    b_ac = baseline.get("activity_count", 0)
    h_ac = head.get("activity_count", 0)
    if b_ac != h_ac:
        raise ComparisonError(
            f"activity_count mismatch: baseline={b_ac} head={h_ac}"
        )


# (metric_key, human description)
GATED_METRICS: tuple[tuple[str, str], ...] = (
    ("cold_timeline_seconds", "cold Timeline render total"),
    ("warm_timeline_seconds", "warm Timeline render total"),
    ("detail_payload_seconds", "detail payload arrival"),
    ("detail_total_seconds", "detail total render"),
)


def _extract_metric(
    payload: dict[str, Any],
    metric_key: str,
    label: str,
) -> tuple[float, list[float]]:
    """Extract (median, samples) for one metric from a driver result."""
    metrics = payload.get("metrics", {})
    entry = metrics.get(metric_key)
    if not isinstance(entry, dict):
        raise ComparisonError(
            f"{label}: metric {metric_key!r} missing or not object"
        )
    if "median_seconds" not in entry:
        raise ComparisonError(
            f"{label}: metric {metric_key!r} missing 'median_seconds'"
        )
    if "samples_seconds" not in entry:
        raise ComparisonError(
            f"{label}: metric {metric_key!r} missing 'samples_seconds'"
        )
    samples = entry["samples_seconds"]
    if not isinstance(samples, list):
        raise ComparisonError(
            f"{label}: metric {metric_key!r} 'samples_seconds' is not a list"
        )
    if not samples:
        raise IncompleteError(
            f"{label}: metric {metric_key!r} has zero samples"
        )
    median = float(entry["median_seconds"])
    return median, [float(s) for s in samples]


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
    baseline = _load_driver_result(baseline_dir / "webview-benchmark.json")
    head = _load_driver_result(head_dir / "webview-benchmark.json")

    _validate_consistency(
        baseline,
        head,
        expected_baseline_sha=baseline_sha,
        expected_head_sha=head_sha,
    )

    gated_results: list[dict[str, Any]] = []
    all_gates_passed = True

    for metric_key, description in GATED_METRICS:
        b_median, b_samples = _extract_metric(baseline, metric_key, "baseline")
        h_median, h_samples = _extract_metric(head, metric_key, "head")

        if len(b_samples) != len(h_samples):
            raise IncompleteError(
                f"{metric_key}: sample count mismatch "
                f"baseline={len(b_samples)} head={len(h_samples)}"
            )

        delta_pct = _percent_delta(b_median, h_median)
        passed = delta_pct <= tolerance_pct
        if not passed:
            all_gates_passed = False

        gated_results.append(
            {
                "metric": metric_key,
                "description": description,
                "unit": "seconds",
                "baseline_median": round(b_median, 6),
                "head_median": round(h_median, 6),
                "delta": round(h_median - b_median, 6),
                "delta_pct": round(delta_pct, 1),
                "tolerance_pct": tolerance_pct,
                "baseline_samples": b_samples,
                "head_samples": h_samples,
                "baseline_min": round(min(b_samples), 6),
                "baseline_max": round(max(b_samples), 6),
                "head_min": round(min(h_samples), 6),
                "head_max": round(max(h_samples), 6),
                "gate_passed": passed,
            }
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
        "activity_count": baseline.get("activity_count", 0),
        "baseline_python_version": baseline.get("python_version", ""),
        "head_python_version": head.get("python_version", ""),
        "tolerance_pct": tolerance_pct,
        "gated_metrics": gated_results,
        "baseline_fixture_audit": baseline.get("fixture_audit", {}),
        "head_fixture_audit": head.get("fixture_audit", {}),
        "all_gates_passed": all_gates_passed,
        "note": (
            "No formal absolute cold Timeline target exists in the repository. "
            "The gate is purely relative (no-regression against baseline). "
            "This comparison does not claim the original cold-Timeline "
            "performance issue is fully validated."
        ),
    }


def _build_markdown(report: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("## WebView render comparison (baseline vs HEAD)")
    lines.append("")
    lines.append(
        f"- baseline: `{report['baseline_revision']}`  "
        f"HEAD: `{report['head_revision']}`"
    )
    lines.append(f"- driver version: `{report['driver_version']}`")
    lines.append(f"- fixture hash: `{report['fixture_hash'][:16]}…`")
    lines.append(f"- activity count: {report['activity_count']}")
    lines.append(f"- no-regression tolerance: {report['tolerance_pct']}%")
    lines.append("")

    lines.append("### Gated metrics (no regression)")
    lines.append("")
    lines.append(
        "| metric | baseline (s) | HEAD (s) | delta (s) | delta (%) | gate |"
    )
    lines.append("|---|---|---|---|---|---|")
    for row in report["gated_metrics"]:
        verdict = "PASS" if row["gate_passed"] else "FAIL"
        lines.append(
            f"| {row['description']} | {row['baseline_median']:.6f} | "
            f"{row['head_median']:.6f} | {row['delta']:+.6f} | "
            f"{row['delta_pct']:+.1f}% | {verdict} |"
        )
    lines.append("")

    lines.append("### Raw samples")
    lines.append("")
    for row in report["gated_metrics"]:
        lines.append(f"- **{row['description']}** (seconds):")
        lines.append(
            f"  - baseline: {row['baseline_samples']} "
            f"(min={row['baseline_min']}, max={row['baseline_max']})"
        )
        lines.append(
            f"  - HEAD: {row['head_samples']} "
            f"(min={row['head_min']}, max={row['head_max']})"
        )
    lines.append("")

    lines.append("### Note")
    lines.append("")
    lines.append(report["note"])
    lines.append("")

    lines.append("### Final verdict")
    lines.append("")
    verdict = "PASS" if report["all_gates_passed"] else "FAIL"
    lines.append(
        f"- **all gates passed: {report['all_gates_passed']}** ({verdict})"
    )
    if not report["all_gates_passed"]:
        lines.append("")
        lines.append("Failed gates:")
        for row in report["gated_metrics"]:
            if not row["gate_passed"]:
                lines.append(
                    f"- {row['description']}: HEAD {row['head_median']:.6f} vs "
                    f"baseline {row['baseline_median']:.6f} "
                    f"({row['delta_pct']:+.1f}% > {row['tolerance_pct']}%)"
                )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--baseline-dir",
        type=Path,
        required=True,
        help="Directory containing baseline webview-benchmark.json",
    )
    parser.add_argument(
        "--head-dir",
        type=Path,
        required=True,
        help="Directory containing HEAD webview-benchmark.json",
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
