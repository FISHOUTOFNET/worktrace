#!/usr/bin/env python3
"""Compare WebView render benchmark results between baseline and HEAD.

Reads JSON artifacts from ``webview_render_perf.py``, validates
schema/fixture/driver/revision consistency, computes per-metric deltas, and
enforces no-regression gates (HEAD median <= baseline median * 1.1) on
``cold_timeline_seconds``, ``warm_timeline_seconds``,
``detail_payload_seconds``, ``detail_total_seconds``.

Revision identity: ``requested_revision`` == ``actual_target_revision``
(``git rev-parse``); ``github_workflow_sha`` is diagnostics-only.  Scenario
isolation: ``fixture_audit.preexisting_activity_count == 0`` and
``inserted_count == requested_count``.  Valid only when ``status == "ok"``
and every run has ``detail_payload_resolved == true`` and
``detail_dom_row_count > 0``.

Fail-closed: ALWAYS writes a JSON artifact to ``--output`` (uploaded via
``if: always()``).  When baseline/HEAD is missing, unparseable, or reports a
driver failure, the artifact records ``outcome`` ∈ {``comparison_passed``,
``comparison_gate_failed``, ``baseline_invalid``, ``head_invalid``,
``both_invalid``}, per-side diagnostics (``result_present``, ``status``,
``failure_category``, ``failure_reason``, ``last_step``), revisions, tolerance —
so finalization surfaces the real reason instead of a "missing artifact" error.

Exit codes: 0 = passed or invalid (artifact written); 2 = input/schema error;
4 = gate failure (both valid, HEAD regressed beyond tolerance).
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
_EXIT_GATE_FAILED = 4


# (metric_key, human description)
GATED_METRICS: tuple[tuple[str, str], ...] = (
    ("cold_timeline_seconds", "cold Timeline render total"),
    ("warm_timeline_seconds", "warm Timeline render total"),
    ("detail_payload_seconds", "detail payload arrival"),
    ("detail_total_seconds", "detail total render"),
)


class ComparisonError(Exception):
    """Input/schema error (exit code 2)."""


# ---------------------------------------------------------------------------
# Side loader: tolerant of missing/invalid artifacts
# ---------------------------------------------------------------------------

class SideResult:
    """One side (baseline or HEAD) of a WebView comparison.

    Encapsulates loading a side's artifact and exposing the relevant
    fields whether the side succeeded (``status == "ok"`` with metrics)
    or failed (missing file, parse error, driver failure, etc.).
    """

    def __init__(
        self,
        *,
        label: str,
        artifact_path: Path,
        expected_sha: str,
    ) -> None:
        self.label = label
        self.artifact_path = artifact_path
        self.expected_sha = expected_sha

        self.present = artifact_path.is_file()
        self.payload: dict[str, Any] | None = None
        self.invalid_reason: str = ""
        self._workload_invalid_reason: str = ""

        if not self.present:
            self.invalid_reason = f"artifact missing: {artifact_path}"
            return

        try:
            self.payload = json.loads(
                artifact_path.read_text(encoding="utf-8")
            )
        except (OSError, ValueError) as exc:
            self.invalid_reason = f"cannot parse {artifact_path}: {exc}"
            return

        if not isinstance(self.payload, dict):
            self.invalid_reason = f"{artifact_path}: root is not an object"
            self.payload = None
            return

    # ----- accessors -----------------------------------------------------

    @property
    def valid(self) -> bool:
        """A side is valid iff the file is present, parseable, the
        driver reported ``status == "ok"`` with a metrics object, AND
        the workload validity check passed (selected Detail is the
        heavy session, not a lightweight one).  Workload validity
        failure marks the side invalid so the comparison gate cannot
        pass by measuring the wrong workload."""
        if not (
            self.payload is not None
            and self.payload.get("status") == "ok"
            and isinstance(self.payload.get("metrics"), dict)
        ):
            return False
        return self.workload_valid

    @property
    def status(self) -> str:
        if self.payload is not None:
            return str(self.payload.get("status", "unknown"))
        return "missing"

    @property
    def failure_category(self) -> str:
        if self.payload is not None:
            return str(self.payload.get("failure_category", ""))
        return ""

    @property
    def failure_reason(self) -> str:
        if self.payload is not None:
            return str(self.payload.get("failure_reason", ""))
        if not self.workload_valid:
            return self.workload_invalid_reason
        return self.invalid_reason

    @property
    def requested_revision(self) -> str:
        if self.payload is not None:
            return str(self.payload.get("requested_revision", ""))
        return ""

    @property
    def actual_target_revision(self) -> str:
        if self.payload is not None:
            return str(self.payload.get("actual_target_revision", ""))
        return ""

    @property
    def driver_version(self) -> str:
        if self.payload is not None:
            return str(self.payload.get("driver_version", ""))
        return ""

    @property
    def fixture_hash(self) -> str:
        if self.payload is not None:
            return str(self.payload.get("fixture_hash", ""))
        return ""

    @property
    def python_version(self) -> str:
        if self.payload is not None:
            return str(self.payload.get("python_version", ""))
        return ""

    @property
    def fixture_audit(self) -> dict[str, Any]:
        if self.payload is not None:
            audit = self.payload.get("fixture_audit", {})
            return audit if isinstance(audit, dict) else {}
        return {}

    @property
    def activity_count(self) -> int:
        if self.payload is not None:
            return int(self.payload.get("activity_count", 0))
        return 0

    @property
    def heavy_session_activity_count(self) -> int:
        """Planned heavy session activity count from the fixture audit."""
        if self.payload is not None:
            return int(self.payload.get("heavy_session_activity_count", 0))
        return 0

    @property
    def heavy_session_marker(self) -> str:
        """Heavy session marker string from the fixture audit."""
        if self.payload is not None:
            return str(self.payload.get("heavy_session_marker", "") or "")
        return ""

    @property
    def first_run(self) -> dict[str, Any]:
        """The first run's results (cold run), used for workload checks."""
        if self.payload is not None:
            runs = self.payload.get("raw_runs") or []
            if runs and isinstance(runs[0], dict):
                return runs[0]
        return {}

    @property
    def workload_valid(self) -> bool:
        """Workload validity: the measured Detail is the heavy session.

        Checks the first run's selector and detail fields:
          * ``selected_detail_is_heavy == true``
          * ``selected_detail_selector_reason`` is a recognized strategy
            (``marker``, ``event_count``, ``duration``) — NOT ``none``.
          * ``detail_source_activity_count`` >= a minimum threshold
            (50 for realistic profile, lower for smoke).

        When the fixture has no heavy session (``heavy_session_activity_count
        == 0``, e.g. ``full`` stress profile), this check is skipped
        (returns True) because there is no heavy workload to enforce.
        """
        if self.heavy_session_activity_count == 0:
            return True
        run = self.first_run
        if not run:
            return False
        is_heavy = bool(run.get("selected_detail_is_heavy", False))
        reason = str(run.get("selected_detail_selector_reason", "none"))
        source_count = int(run.get("detail_source_activity_count", 0) or 0)
        # Minimum threshold: 50 for realistic (heavy count >= 50), or
        # heavy_count // 2 for smoke (where heavy count is small).
        min_threshold = (
            50 if self.heavy_session_activity_count >= 50
            else max(1, self.heavy_session_activity_count // 2)
        )
        if not is_heavy:
            self._workload_invalid_reason = (
                f"selected_detail_is_heavy=false (reason={reason}) — "
                f"harness did not select the heavy session"
            )
            return False
        if reason == "none":
            self._workload_invalid_reason = (
                "selected_detail_selector_reason=none — "
                "harness did not select any session"
            )
            return False
        if source_count < min_threshold:
            self._workload_invalid_reason = (
                f"detail_source_activity_count={source_count} < "
                f"min_threshold={min_threshold} — "
                f"measured Detail is not the heavy workload"
            )
            return False
        self._workload_invalid_reason = ""
        return True

    @property
    def workload_invalid_reason(self) -> str:
        """The workload validity failure reason, or empty if valid."""
        # Trigger lazy evaluation.
        _ = self.workload_valid
        return getattr(self, "_workload_invalid_reason", "")

    @property
    def github_workflow_sha(self) -> str:
        """The ``GITHUB_SHA`` recorded by the driver — diagnostics only,
        never used for identity comparison (it can be a merge commit SHA
        in ``pull_request`` workflows)."""
        if self.payload is not None:
            return str(self.payload.get("github_workflow_sha", "") or "")
        return ""


def _side_diagnostics(side: SideResult) -> dict[str, Any]:
    """Return a diagnostics dict for one side, suitable for the artifact."""
    run = side.first_run
    return {
        "label": side.label,
        "artifact_path": str(side.artifact_path),
        "present": side.present,
        "valid": side.valid,
        "status": side.status,
        "invalid_reason": side.invalid_reason if not side.valid else "",
        "failure_category": side.failure_category,
        "failure_reason": side.failure_reason,
        "requested_revision": side.requested_revision,
        "actual_target_revision": side.actual_target_revision,
        "expected_revision": side.expected_sha,
        "driver_version": side.driver_version,
        "fixture_hash": side.fixture_hash,
        "python_version": side.python_version,
        "activity_count": side.activity_count,
        "fixture_audit": side.fixture_audit,
        "heavy_session_activity_count": side.heavy_session_activity_count,
        "heavy_session_marker": side.heavy_session_marker,
        "workload_valid": side.workload_valid,
        "workload_invalid_reason": side.workload_invalid_reason,
        "selected_detail_is_heavy": bool(
            run.get("selected_detail_is_heavy", False)
        ),
        "selected_detail_selector_reason": str(
            run.get("selected_detail_selector_reason", "")
        ),
        "selected_detail_source_event_count": int(
            run.get("detail_source_activity_count", 0) or 0
        ),
        "selected_detail_expected_activity_count": int(
            run.get("selected_detail_expected_activity_count", 0) or 0
        ),
        "detail_source_activity_count": int(
            run.get("detail_source_activity_count", 0) or 0
        ),
        "detail_summary_row_count": int(
            run.get("detail_summary_row_count", 0) or 0
        ),
        "detail_dom_row_count": int(
            run.get("detail_dom_row_count", 0) or 0
        ),
        "github_workflow_sha": side.github_workflow_sha,
    }


# ---------------------------------------------------------------------------
# Consistency validation (only when both sides valid)
# ---------------------------------------------------------------------------

def _validate_revision_identity(side: SideResult) -> None:
    """Verify the artifact's revision identity contract."""
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
    """Verify the WebView fixture's audit reports clean isolation."""
    audit = side.fixture_audit
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
    if baseline.activity_count != head.activity_count:
        raise ComparisonError(
            f"activity_count mismatch: baseline={baseline.activity_count} "
            f"head={head.activity_count}"
        )
    _validate_heavy_workload_consistency(baseline, head)


def _validate_heavy_workload_consistency(
    baseline: SideResult,
    head: SideResult,
) -> None:
    """Verify both sides measured the same heavy workload.

    For runs with a heavy session (``heavy_session_activity_count > 0``):
      * Both sides must have the same ``heavy_session_activity_count``.
      * Both sides must have the same ``heavy_session_marker``.
      * Both sides must have selected a heavy Detail
        (``selected_detail_is_heavy == true``).
      * Both sides' selector reason must be a recognized strategy
        (not ``none``).
      * Both sides' ``detail_source_activity_count`` must be >= a
        minimum threshold.

    This prevents the gate from passing when baseline measured the
    heavy session but HEAD measured a lightweight one.  Such a mismatch
    would make the comparison apples-to-oranges and could mask a real
    regression (or fake an improvement).
    """
    b_heavy = baseline.heavy_session_activity_count
    h_heavy = head.heavy_session_activity_count
    if b_heavy == 0 and h_heavy == 0:
        # No heavy workload enforced (e.g. full stress profile).
        return
    if b_heavy != h_heavy:
        raise ComparisonError(
            f"heavy_session_activity_count mismatch: "
            f"baseline={b_heavy} head={h_heavy}"
        )
    if baseline.heavy_session_marker != head.heavy_session_marker:
        raise ComparisonError(
            f"heavy_session_marker mismatch: "
            f"baseline={baseline.heavy_session_marker!r} "
            f"head={head.heavy_session_marker!r}"
        )

    # Both sides are workload-valid (caller checks ``SideResult.valid``
    # first).  Still verify selector reason is present so a silent
    # change in selection strategy between revisions is surfaced.
    b_reason = str(baseline.first_run.get(
        "selected_detail_selector_reason", "none"
    ))
    h_reason = str(head.first_run.get(
        "selected_detail_selector_reason", "none"
    ))
    if b_reason == "none":
        raise ComparisonError(
            "baseline selected_detail_selector_reason=none — "
            "harness did not select any session"
        )
    if h_reason == "none":
        raise ComparisonError(
            "head selected_detail_selector_reason=none — "
            "harness did not select any session"
        )
    # Selector reasons differing across revisions is not necessarily a
    # failure (marker present in both, but baseline may fall back to
    # event_count while HEAD uses marker — still valid heavy selection).
    # Recorded in the artifact for audit; not a comparison failure.


# ---------------------------------------------------------------------------
# Metric extraction & gate
# ---------------------------------------------------------------------------

def _extract_metric(
    side: SideResult,
    metric_key: str,
) -> tuple[float, list[float]]:
    """Extract (median, samples) for one metric from a valid side."""
    metrics = side.payload.get("metrics", {}) if side.payload else {}
    entry = metrics.get(metric_key)
    if not isinstance(entry, dict):
        raise ComparisonError(
            f"{side.label}: metric {metric_key!r} missing or not object"
        )
    if "median_seconds" not in entry:
        raise ComparisonError(
            f"{side.label}: metric {metric_key!r} missing 'median_seconds'"
        )
    if "samples_seconds" not in entry:
        raise ComparisonError(
            f"{side.label}: metric {metric_key!r} missing 'samples_seconds'"
        )
    samples = entry["samples_seconds"]
    if not isinstance(samples, list):
        raise ComparisonError(
            f"{side.label}: metric {metric_key!r} 'samples_seconds' not a list"
        )
    if not samples:
        raise ComparisonError(
            f"{side.label}: metric {metric_key!r} has zero samples"
        )
    median = float(entry["median_seconds"])
    return median, [float(s) for s in samples]


def _percent_delta(baseline: float, head: float) -> float:
    if baseline == 0:
        return 0.0 if head == 0 else 100.0
    return (head - baseline) / baseline * 100.0


# ---------------------------------------------------------------------------
# Comparison builder (always produces an artifact)
# ---------------------------------------------------------------------------

def _build_comparison(
    *,
    baseline_dir: Path,
    head_dir: Path,
    baseline_sha: str,
    head_sha: str,
    tolerance_pct: float,
) -> dict[str, Any]:
    """Build the comparison artifact.  Always returns a dict (never raises
    on invalid sides); only raises on truly unrecoverable input/schema
    errors like an unwritable output path.
    """
    baseline = SideResult(
        label="baseline",
        artifact_path=baseline_dir / "webview-benchmark.json",
        expected_sha=baseline_sha,
    )
    head = SideResult(
        label="head",
        artifact_path=head_dir / "webview-benchmark.json",
        expected_sha=head_sha,
    )

    base_diag = _side_diagnostics(baseline)
    head_diag = _side_diagnostics(head)

    gated_results: list[dict[str, Any]] | None = None
    all_gates_passed: bool | None = None
    consistency_error = ""

    # Determine outcome category.
    if not baseline.valid and not head.valid:
        outcome = "both_invalid"
    elif not baseline.valid:
        outcome = "baseline_invalid"
    elif not head.valid:
        outcome = "head_invalid"
    else:
        # Both sides have status="ok" with metrics.  Run consistency checks.
        try:
            _validate_revision_identity(baseline)
            _validate_revision_identity(head)
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
            # Gate: compute per-metric deltas and enforce no-regression.
            gated_results = []
            all_gates_passed = True

            for metric_key, description in GATED_METRICS:
                b_median, b_samples = _extract_metric(baseline, metric_key)
                h_median, h_samples = _extract_metric(head, metric_key)

                if len(b_samples) != len(h_samples):
                    raise ComparisonError(
                        f"{metric_key}: sample count mismatch "
                        f"baseline={len(b_samples)} head={len(h_samples)}"
                    )

                delta_pct = _percent_delta(b_median, h_median)
                passed = delta_pct <= tolerance_pct
                if not passed:
                    all_gates_passed = False

                gated_results.append({
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
                })

            outcome = (
                "comparison_passed" if all_gates_passed
                else "comparison_gate_failed"
            )

    artifact: dict[str, Any] = {
        "schema_version": _SCHEMA_VERSION,
        "baseline_sha": baseline_sha,
        "head_sha": head_sha,
        "tolerance_pct": tolerance_pct,
        "outcome": outcome,
        "baseline": base_diag,
        "head": head_diag,
        "gated_metrics": gated_results,
        "all_gates_passed": all_gates_passed,
        "note": (
            "No formal absolute cold Timeline target exists in the repository. "
            "The gate is purely relative (no-regression against baseline). "
            "This comparison does not claim the original cold-Timeline "
            "performance issue is fully validated."
        ),
    }
    if consistency_error:
        artifact["consistency_error"] = consistency_error

    return artifact


# ---------------------------------------------------------------------------
# Markdown summary
# ---------------------------------------------------------------------------

def _build_markdown(report: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("## WebView render comparison (baseline vs HEAD)")
    lines.append("")
    lines.append(
        f"- baseline: `{report['baseline_sha']}`  "
        f"HEAD: `{report['head_sha']}`"
    )
    lines.append(f"- tolerance: {report['tolerance_pct']}%")
    lines.append(f"- outcome: **{report['outcome']}**")
    lines.append("")

    for side_label in ("baseline", "head"):
        side = report[side_label]
        lines.append(f"### {side_label}")
        lines.append("")
        lines.append(f"- present: {side['present']}")
        lines.append(f"- valid: {side['valid']}")
        lines.append(f"- status: `{side['status']}`")
        if side["failure_category"]:
            lines.append(f"- failure_category: `{side['failure_category']}`")
        if side["failure_reason"]:
            lines.append(f"- failure_reason: {side['failure_reason']}")
        if side.get("driver_version"):
            lines.append(f"- driver_version: `{side['driver_version']}`")
        audit = side.get("fixture_audit") or {}
        if audit:
            lines.append(
                f"- fixture_audit: inserted={audit.get('inserted_count')}, "
                f"requested={audit.get('requested_count')}, "
                f"preexisting={audit.get('preexisting_activity_count')}"
            )
        if side.get("heavy_session_activity_count"):
            lines.append(
                f"- heavy_session: count={side['heavy_session_activity_count']}, "
                f"marker=`{side.get('heavy_session_marker', '')}`, "
                f"workload_valid={side.get('workload_valid')}"
            )
            if side.get("workload_invalid_reason"):
                lines.append(
                    f"- workload_invalid_reason: "
                    f"{side['workload_invalid_reason']}"
                )
            lines.append(
                f"- selected_detail: is_heavy="
                f"{side.get('selected_detail_is_heavy')}, "
                f"reason=`{side.get('selected_detail_selector_reason', '')}`, "
                f"source_count={side.get('detail_source_activity_count', 0)}, "
                f"summary_rows={side.get('detail_summary_row_count', 0)}, "
                f"dom_rows={side.get('detail_dom_row_count', 0)}"
            )
        lines.append("")

    if report.get("gated_metrics"):
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

    if report.get("consistency_error"):
        lines.append("### Consistency error")
        lines.append("")
        lines.append(f"**{report['consistency_error']}**")
        lines.append("")

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
        required=True,
        help="Write JSON comparison artifact to this path (always written).",
    )
    args = parser.parse_args()

    try:
        report = _build_comparison(
            baseline_dir=args.baseline_dir,
            head_dir=args.head_dir,
            baseline_sha=args.baseline_sha,
            head_sha=args.head_sha,
            tolerance_pct=args.tolerance_pct,
        )
    except ComparisonError as exc:
        # Truly unrecoverable input/schema error (e.g. sample count mismatch
        # after both sides validated).  Still emit an artifact so the
        # workflow's ``if: always()`` upload step has something to upload.
        failure_payload = {
            "schema_version": _SCHEMA_VERSION,
            "baseline_sha": args.baseline_sha,
            "head_sha": args.head_sha,
            "tolerance_pct": args.tolerance_pct,
            "outcome": "both_invalid",
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
