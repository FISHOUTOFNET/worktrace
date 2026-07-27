#!/usr/bin/env python3
"""Compare ONE product benchmark scenario between baseline and HEAD.

The comparison layer is scenario-scoped: each invocation compares exactly
one scenario (``--scenario``), reading ``result.json`` from the baseline
and HEAD driver output directories.  When ``result.json`` is missing on
either side, the comparison reads ``progress.json`` and ``failure.json``
so the artifact can still report the last completed phase, the failure
category, and any partial samples — instead of just "required artifact
missing".

Scenario → metric mapping
-------------------------
* ``20k_activities``         → ``projection_20k_total_seconds``
* ``10k_contributions``      → ``projection_10k_contributions_seconds``

Cross-revision consistency checks
---------------------------------
* driver_version matches between baseline and HEAD
* fixture_hash matches between baseline and HEAD
* requested_revision == actual_target_revision within each artifact
* actual_target_revision matches the expected SHA from the CLI
* Python major.minor matches between baseline and HEAD
* fixture_audit.preexisting_activity_count == 0
* fixture_audit.inserted_count == requested_count
* fixture_audit.connection_count >= 1, commit_count >= 1
* sample count matches between baseline and HEAD (when both have results)
* consistency_hash matches between baseline and HEAD (when both have results)

Final comparison artifact
-------------------------
The comparison ALWAYS writes a JSON artifact to ``--output`` (the workflow
uploads it via ``if: always()``).  The artifact records:

* ``outcome`` ∈ {``comparison_passed``, ``comparison_gate_failed``,
  ``baseline_invalid``, ``head_invalid``, ``both_invalid``}
* per-metric gate results (when both sides have valid results)
* last phase, failure category, failure message, completed samples,
  fixture audit, and result-missing flag for each side
* the expected and actual revisions
* the tolerance percentage

Exit codes
----------
0  comparison passed (or one side invalid but artifact written)
2  input/schema error (e.g. scenario unknown, output path unwritable)
4  gate failure (both sides valid but HEAD regressed beyond tolerance)

When one or both sides are invalid, the comparison writes the artifact
and exits 0 — the gate cannot run when inputs are invalid, and the
artifact's ``outcome`` field already records the failure mode.  This
lets the workflow's ``if: always()`` finalization step surface the
real reason instead of masking it with a "missing artifact" error.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

_SCHEMA_VERSION = 3
_EXIT_OK = 0
_EXIT_INPUT_SCHEMA = 2
_EXIT_GATE_FAILED = 4


# Scenario → (metric_key, description, value_field, sample_field, unit).
_SCENARIO_METRICS: dict[str, tuple[str, str, str, str, str]] = {
    "20k_activities": (
        "projection_20k_total_seconds",
        "20k activities projection total",
        "median_seconds",
        "samples_seconds",
        "seconds",
    ),
    "10k_contributions": (
        "projection_10k_contributions_seconds",
        "10k contributions projection total",
        "median_seconds",
        "samples_seconds",
        "seconds",
    ),
}


class ComparisonError(Exception):
    """Input/schema error (exit code 2)."""


# ---------------------------------------------------------------------------
# Side loader: reads result.json OR progress.json + failure.json
# ---------------------------------------------------------------------------

class SideResult:
    """One side (baseline or HEAD) of a scenario comparison.

    Encapsulates the logic for loading a side's artifacts and exposing
    the relevant fields whether the side succeeded (result.json present)
    or failed (only progress.json / failure.json present).
    """

    def __init__(
        self,
        *,
        label: str,
        output_dir: Path,
        expected_sha: str,
        scenario: str,
        progress_path: Path | None = None,
        failure_path: Path | None = None,
    ) -> None:
        self.label = label
        self.output_dir = output_dir
        self.expected_sha = expected_sha
        self.scenario = scenario
        self.result_path = output_dir / "result.json"
        self.progress_path = progress_path or (output_dir / "progress.json")
        self.failure_path = failure_path or (output_dir / "failure.json")

        self.result_present = self.result_path.is_file()
        self.progress_present = self.progress_path.is_file()
        self.failure_present = self.failure_path.is_file()

        self.result: dict[str, Any] | None = None
        self.progress: dict[str, Any] | None = None
        self.failure: dict[str, Any] | None = None

        if self.result_present:
            try:
                self.result = json.loads(
                    self.result_path.read_text(encoding="utf-8")
                )
            except (OSError, ValueError) as exc:
                raise ComparisonError(
                    f"{label}: cannot parse {self.result_path}: {exc}"
                )
        if self.progress_present:
            try:
                self.progress = json.loads(
                    self.progress_path.read_text(encoding="utf-8")
                )
            except (OSError, ValueError) as exc:
                raise ComparisonError(
                    f"{label}: cannot parse {self.progress_path}: {exc}"
                )
        if self.failure_present:
            try:
                self.failure = json.loads(
                    self.failure_path.read_text(encoding="utf-8")
                )
            except (OSError, ValueError) as exc:
                raise ComparisonError(
                    f"{label}: cannot parse {self.failure_path}: {exc}"
                )

        if not self.result_present and not self.progress_present:
            raise ComparisonError(
                f"{label}: neither result.json nor progress.json present in "
                f"{output_dir}"
            )

    # ----- accessors -----------------------------------------------------

    @property
    def valid(self) -> bool:
        """A side is valid iff result.json is present and well-formed."""
        return self.result is not None

    @property
    def invalid_reason(self) -> str:
        if self.valid:
            return ""
        if self.failure_present and self.failure:
            cat = self.failure.get("failure_category", "unknown")
            msg = self.failure.get("failure_message", "")
            return f"{cat}: {msg}"
        if self.progress_present and self.progress:
            phase = self.progress.get("phase", "unknown")
            return f"driver did not complete (last phase: {phase})"
        return "no result.json and no diagnostics"

    @property
    def last_phase(self) -> str:
        if self.progress_present and self.progress:
            return self.progress.get("phase", "unknown")
        if self.result is not None:
            return "result_completed"
        return "unknown"

    @property
    def failure_category(self) -> str:
        if self.failure_present and self.failure:
            return self.failure.get("failure_category", "")
        return ""

    @property
    def failure_message(self) -> str:
        if self.failure_present and self.failure:
            return self.failure.get("failure_message", "")
        return ""

    @property
    def completed_samples(self) -> int:
        if self.progress_present and self.progress:
            return int(self.progress.get("completed_samples", 0))
        if self.result is not None:
            metric_key = _SCENARIO_METRICS[self.scenario][0]
            metric = self.result.get("metrics", {}).get(metric_key, {})
            return len(metric.get("samples_seconds", []))
        return 0

    @property
    def fixture_audit(self) -> dict[str, Any]:
        if self.result is not None:
            return self.result.get("fixture_audit", {}) or {}
        if self.progress_present and self.progress:
            return self.progress.get("fixture_audit", {}) or {}
        return {}

    @property
    def requested_revision(self) -> str:
        for source in (self.result, self.progress):
            if source and source.get("requested_revision"):
                return str(source["requested_revision"])
        return ""

    @property
    def actual_target_revision(self) -> str:
        for source in (self.result, self.progress):
            if source and source.get("actual_target_revision"):
                return str(source["actual_target_revision"])
        return ""

    @property
    def driver_version(self) -> str:
        for source in (self.result, self.progress):
            if source and source.get("driver_version"):
                return str(source["driver_version"])
        return ""

    @property
    def fixture_hash(self) -> str:
        for source in (self.result, self.progress):
            if source and source.get("fixture_hash"):
                return str(source["fixture_hash"])
        return ""

    @property
    def python_version(self) -> str:
        if self.result is not None:
            return self.result.get("python_version", "")
        return ""

    @property
    def runner_metadata(self) -> dict[str, Any]:
        for source in (self.result, self.progress):
            if source and source.get("runner_metadata"):
                return source["runner_metadata"]
        return {}


# ---------------------------------------------------------------------------
# Consistency validation (only when both sides valid)
# ---------------------------------------------------------------------------

def _validate_revision_identity(side: SideResult) -> None:
    """Verify requested == actual == expected for one side."""
    requested = side.requested_revision
    actual = side.actual_target_revision
    if not requested or not actual:
        raise ComparisonError(
            f"{side.label}: missing requested_revision or "
            f"actual_target_revision (requested={requested!r}, "
            f"actual={actual!r})"
        )
    if requested != actual:
        raise ComparisonError(
            f"{side.label}: requested_revision {requested!r} != "
            f"actual_target_revision {actual!r}"
        )
    if actual != side.expected_sha:
        raise ComparisonError(
            f"{side.label}: actual_target_revision {actual!r} != "
            f"expected {side.expected_sha!r}"
        )


def _validate_scenario_isolation(side: SideResult) -> None:
    """Verify the side's fixture_audit reports clean isolation."""
    audit = side.fixture_audit
    if not isinstance(audit, dict):
        raise ComparisonError(
            f"{side.label}: fixture_audit is not an object"
        )
    if not audit:
        raise ComparisonError(f"{side.label}: fixture_audit is empty")
    preexisting = audit.get("preexisting_activity_count")
    if preexisting != 0:
        raise ComparisonError(
            f"{side.label}: preexisting_activity_count={preexisting} "
            f"(expected 0)"
        )
    requested = audit.get("requested_count", 0)
    inserted = audit.get("inserted_count", 0)
    if inserted != requested:
        raise ComparisonError(
            f"{side.label}: inserted_count={inserted} != "
            f"requested_count={requested}"
        )
    if audit.get("connection_count", 0) < 1:
        raise ComparisonError(f"{side.label}: connection_count < 1")
    if audit.get("commit_count", 0) < 1:
        raise ComparisonError(f"{side.label}: commit_count < 1")


def _validate_cross_revision_consistency(
    baseline: SideResult,
    head: SideResult,
) -> None:
    """Cross-check driver version, fixture hash, Python version."""
    if baseline.driver_version != head.driver_version:
        raise ComparisonError(
            f"driver_version mismatch: baseline={baseline.driver_version!r} "
            f"head={head.driver_version!r}"
        )
    if baseline.fixture_hash and head.fixture_hash and \
            baseline.fixture_hash != head.fixture_hash:
        raise ComparisonError(
            f"fixture_hash mismatch: baseline={baseline.fixture_hash!r} "
            f"head={head.fixture_hash!r}"
        )
    b_py_mm = ".".join(baseline.python_version.split(".")[:2]) \
        if baseline.python_version else ""
    h_py_mm = ".".join(head.python_version.split(".")[:2]) \
        if head.python_version else ""
    if b_py_mm and h_py_mm and b_py_mm != h_py_mm:
        raise ComparisonError(
            f"python_version mismatch: baseline={b_py_mm!r} "
            f"head={h_py_mm!r}"
        )


# ---------------------------------------------------------------------------
# Metric extraction & gate
# ---------------------------------------------------------------------------

def _extract_metric(
    side: SideResult,
    *,
    metric_key: str,
    value_field: str,
    sample_field: str,
) -> tuple[float, list[float]]:
    metrics = side.result.get("metrics", {}) if side.result else {}
    entry = metrics.get(metric_key)
    if not isinstance(entry, dict):
        raise ComparisonError(
            f"{side.label}: metric {metric_key!r} missing or not object"
        )
    if value_field not in entry:
        raise ComparisonError(
            f"{side.label}: metric {metric_key!r} missing {value_field!r}"
        )
    if sample_field not in entry:
        raise ComparisonError(
            f"{side.label}: metric {metric_key!r} missing {sample_field!r}"
        )
    samples = entry[sample_field]
    if not isinstance(samples, list):
        raise ComparisonError(
            f"{side.label}: metric {metric_key!r} {sample_field!r} not a list"
        )
    if not samples:
        raise ComparisonError(
            f"{side.label}: metric {metric_key!r} has zero samples"
        )
    median = float(entry[value_field])
    return median, [float(s) for s in samples]


def _percent_delta(baseline: float, head: float) -> float:
    if baseline == 0:
        return 0.0 if head == 0 else 100.0
    return (head - baseline) / baseline * 100.0


# ---------------------------------------------------------------------------
# Side diagnostics (used in artifact even when invalid)
# ---------------------------------------------------------------------------

def _side_diagnostics(side: SideResult) -> dict[str, Any]:
    """Return a diagnostics dict for one side, suitable for the artifact."""
    return {
        "label": side.label,
        "result_present": side.result_present,
        "progress_present": side.progress_present,
        "failure_present": side.failure_present,
        "valid": side.valid,
        "invalid_reason": side.invalid_reason,
        "last_phase": side.last_phase,
        "failure_category": side.failure_category,
        "failure_message": side.failure_message,
        "completed_samples": side.completed_samples,
        "fixture_audit": side.fixture_audit,
        "requested_revision": side.requested_revision,
        "actual_target_revision": side.actual_target_revision,
        "expected_revision": side.expected_sha,
        "driver_version": side.driver_version,
        "fixture_hash": side.fixture_hash,
        "python_version": side.python_version,
        "runner_metadata": side.runner_metadata,
        "output_dir": str(side.output_dir),
    }


# ---------------------------------------------------------------------------
# Comparison builder
# ---------------------------------------------------------------------------

def _build_comparison(
    *,
    scenario: str,
    baseline_dir: Path,
    head_dir: Path,
    baseline_sha: str,
    head_sha: str,
    tolerance_pct: float,
    baseline_progress: Path | None = None,
    baseline_failure: Path | None = None,
    head_progress: Path | None = None,
    head_failure: Path | None = None,
) -> dict[str, Any]:
    if scenario not in _SCENARIO_METRICS:
        raise ComparisonError(
            f"unknown scenario {scenario!r}; expected one of "
            f"{sorted(_SCENARIO_METRICS)}"
        )

    metric_key, description, value_field, sample_field, unit = \
        _SCENARIO_METRICS[scenario]

    baseline = SideResult(
        label="baseline",
        output_dir=baseline_dir,
        expected_sha=baseline_sha,
        scenario=scenario,
        progress_path=baseline_progress,
        failure_path=baseline_failure,
    )
    head = SideResult(
        label="head",
        output_dir=head_dir,
        expected_sha=head_sha,
        scenario=scenario,
        progress_path=head_progress,
        failure_path=head_failure,
    )

    # Validate revision identity on each side independently.  Even if a
    # side has no result.json, its progress.json records the verified
    # revision, so we can still detect a SHA mismatch.
    _validate_revision_identity(baseline)
    _validate_revision_identity(head)

    base_diag = _side_diagnostics(baseline)
    head_diag = _side_diagnostics(head)

    gated_result: dict[str, Any] | None = None
    consistency_match: bool | None = None
    consistency_error = ""

    # Determine outcome category.
    if not baseline.valid and not head.valid:
        outcome = "both_invalid"
    elif not baseline.valid:
        outcome = "baseline_invalid"
    elif not head.valid:
        outcome = "head_invalid"
    else:
        # Both valid: run consistency checks and gate.
        try:
            _validate_cross_revision_consistency(baseline, head)
            _validate_scenario_isolation(baseline)
            _validate_scenario_isolation(head)
        except ComparisonError as exc:
            # Consistency violations make the gate un-runnable.  Record
            # the error and fall through to artifact writing — do NOT
            # re-raise, or the workflow's if: always() upload step
            # would have no artifact to surface.
            outcome = "both_invalid"
            consistency_error = str(exc)
        else:
            b_median, b_samples = _extract_metric(
                baseline,
                metric_key=metric_key,
                value_field=value_field,
                sample_field=sample_field,
            )
            h_median, h_samples = _extract_metric(
                head,
                metric_key=metric_key,
                value_field=value_field,
                sample_field=sample_field,
            )

            if len(b_samples) != len(h_samples):
                raise ComparisonError(
                    f"{metric_key}: sample count mismatch "
                    f"baseline={len(b_samples)} head={len(h_samples)}"
                )

            delta_pct = _percent_delta(b_median, h_median)
            gate_passed = delta_pct <= tolerance_pct
            outcome = (
                "comparison_passed" if gate_passed
                else "comparison_gate_failed"
            )

            b_consistency_hash = (
                baseline.result.get("metrics", {})
                .get(metric_key, {})
                .get("consistency_hash", "")
                if baseline.result else ""
            )
            h_consistency_hash = (
                head.result.get("metrics", {})
                .get(metric_key, {})
                .get("consistency_hash", "")
                if head.result else ""
            )
            consistency_match = b_consistency_hash == h_consistency_hash

            gated_result = {
                "metric": metric_key,
                "description": description,
                "unit": unit,
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
                "gate_passed": gate_passed,
                "baseline_consistency_hash": b_consistency_hash,
                "head_consistency_hash": h_consistency_hash,
            }

    # ------------------------------------------------------------------
    # Build artifact (always written, even on consistency errors)
    # ------------------------------------------------------------------
    artifact: dict[str, Any] = {
        "schema_version": _SCHEMA_VERSION,
        "scenario": scenario,
        "metric_key": metric_key,
        "baseline_sha": baseline_sha,
        "head_sha": head_sha,
        "tolerance_pct": tolerance_pct,
        "outcome": outcome,
        "baseline": base_diag,
        "head": head_diag,
        "gated_metric": gated_result,
        "consistency_match": consistency_match,
    }
    if consistency_error:
        artifact["consistency_error"] = consistency_error

    return artifact


# ---------------------------------------------------------------------------
# Markdown summary
# ---------------------------------------------------------------------------

def _build_markdown(report: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append(
        f"## Product benchmark comparison — scenario "
        f"`{report['scenario']}`"
    )
    lines.append("")
    lines.append(
        f"- baseline: `{report['baseline_sha']}`  "
        f"HEAD: `{report['head_sha']}`"
    )
    lines.append(f"- metric: `{report['metric_key']}`")
    lines.append(f"- tolerance: {report['tolerance_pct']}%")
    lines.append(f"- outcome: **{report['outcome']}**")
    lines.append("")

    for side_label in ("baseline", "head"):
        side = report[side_label]
        lines.append(f"### {side_label}")
        lines.append("")
        lines.append(f"- result_present: {side['result_present']}")
        lines.append(f"- valid: {side['valid']}")
        lines.append(f"- last_phase: `{side['last_phase']}`")
        if side["failure_category"]:
            lines.append(f"- failure_category: `{side['failure_category']}`")
            lines.append(
                f"- failure_message: {side['failure_message']}"
            )
        lines.append(f"- completed_samples: {side['completed_samples']}")
        audit = side.get("fixture_audit") or {}
        if audit:
            lines.append(
                f"- fixture_audit: inserted={audit.get('inserted_count')}, "
                f"requested={audit.get('requested_count')}, "
                f"preexisting={audit.get('preexisting_activity_count')}, "
                f"connections={audit.get('connection_count')}, "
                f"commits={audit.get('commit_count')}"
            )
        lines.append("")

    if report.get("gated_metric"):
        row = report["gated_metric"]
        lines.append("### Gated metric")
        lines.append("")
        lines.append("| field | value |")
        lines.append("|---|---|")
        lines.append(
            f"| baseline median | {row['baseline_median']:.6f} {row['unit']} |"
        )
        lines.append(
            f"| HEAD median | {row['head_median']:.6f} {row['unit']} |"
        )
        lines.append(
            f"| delta | {row['delta']:+.6f} ({row['delta_pct']:+.1f}%) |"
        )
        verdict = "PASS" if row["gate_passed"] else "FAIL"
        lines.append(f"| gate | {verdict} (tolerance {row['tolerance_pct']}%) |")
        lines.append(
            f"| baseline samples | {row['baseline_samples']} |"
        )
        lines.append(
            f"| HEAD samples | {row['head_samples']} |"
        )
        lines.append(
            f"| consistency match | {report.get('consistency_match')} |"
        )
        lines.append("")
    else:
        lines.append("### No gated metric")
        lines.append("")
        lines.append(
            "One or both sides are invalid; the gate was not executed."
        )
        if report.get("consistency_error"):
            lines.append(f"\n**Consistency error:** {report['consistency_error']}")
        lines.append("")

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare ONE product benchmark scenario (baseline vs HEAD)"
    )
    parser.add_argument(
        "--scenario",
        choices=sorted(_SCENARIO_METRICS.keys()),
        required=True,
        help="Scenario to compare.",
    )
    parser.add_argument(
        "--baseline-dir",
        type=Path,
        required=True,
        help="Directory containing baseline result.json / progress.json",
    )
    parser.add_argument(
        "--head-dir",
        type=Path,
        required=True,
        help="Directory containing HEAD result.json / progress.json",
    )
    parser.add_argument(
        "--baseline-progress",
        type=Path,
        default=None,
        help="Optional explicit path to baseline progress.json "
             "(defaults to <baseline-dir>/progress.json).",
    )
    parser.add_argument(
        "--head-progress",
        type=Path,
        default=None,
        help="Optional explicit path to HEAD progress.json.",
    )
    parser.add_argument(
        "--baseline-failure",
        type=Path,
        default=None,
        help="Optional explicit path to baseline failure.json.",
    )
    parser.add_argument(
        "--head-failure",
        type=Path,
        default=None,
        help="Optional explicit path to HEAD failure.json.",
    )
    parser.add_argument("--baseline-sha", required=True)
    parser.add_argument("--head-sha", required=True)
    parser.add_argument(
        "--tolerance-pct",
        type=float,
        default=10.0,
        help="Maximum allowed regression percentage (default 10).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Write JSON comparison artifact to this path.",
    )
    args = parser.parse_args()

    try:
        report = _build_comparison(
            scenario=args.scenario,
            baseline_dir=args.baseline_dir,
            head_dir=args.head_dir,
            baseline_sha=args.baseline_sha,
            head_sha=args.head_sha,
            tolerance_pct=args.tolerance_pct,
            baseline_progress=args.baseline_progress,
            baseline_failure=args.baseline_failure,
            head_progress=args.head_progress,
            head_failure=args.head_failure,
        )
    except ComparisonError as exc:
        # Input/schema error — still emit an artifact so the workflow's
        # ``if: always()`` upload step has something to upload.
        failure_payload = {
            "schema_version": _SCHEMA_VERSION,
            "scenario": args.scenario,
            "outcome": "both_invalid",
            "baseline_sha": args.baseline_sha,
            "head_sha": args.head_sha,
            "tolerance_pct": args.tolerance_pct,
            "comparison_error": str(exc),
        }
        try:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(
                json.dumps(failure_payload, indent=2) + "\n",
                encoding="utf-8",
            )
        except OSError as write_exc:
            print(
                f"comparison_error: cannot write failure artifact: {write_exc}",
                file=sys.stderr,
            )
            return _EXIT_INPUT_SCHEMA
        print(
            f"comparison_error (input/schema): {exc}",
            file=sys.stderr,
        )
        return _EXIT_INPUT_SCHEMA

    # Always write the artifact.
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    md_text = _build_markdown(report)
    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        with open(step_summary, "a", encoding="utf-8") as fh:
            fh.write(md_text)

    print(md_text)

    if report["outcome"] == "comparison_gate_failed":
        return _EXIT_GATE_FAILED
    return _EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
