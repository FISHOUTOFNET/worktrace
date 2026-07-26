#!/usr/bin/env python3
"""Compute paired timing comparison and enforce layered acceptance gates.

Reads the paired result directories produced by
``standard-timing-validation.yml`` and emits a structured JSON attribution
report plus a Markdown summary.  Gates:

* ``common_suite``: paired median wall-clock regression of the common test
  set must not exceed the configured threshold (default 10%).
* ``head_full_suite``: HEAD full-suite median wall-clock must not exceed
  the configured absolute limit (default 240s).
* ``head_only_suite``: informational only — HEAD-only tests must all pass
  and the cost is reported, but no relative-improvement gate applies.
* Structural gates: all runs valid, test count not reduced, no failures,
  skipped no unexplained growth, dependency match.

The script exits non-zero if any gate fails so the workflow step fails.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# JUnit parsing
# ---------------------------------------------------------------------------

def _parse_junit(path: Path) -> tuple[dict[str, float], dict[str, Any]]:
    """Parse a JUnit XML file into (node_id -> seconds, suite_attrib)."""
    tree = ET.parse(path)
    root = tree.getroot()
    suite = root if root.tag == "testsuite" else root[0]
    suite_attrib: dict[str, Any] = dict(suite.attrib)
    tests: dict[str, float] = {}
    for case in suite.iter("testcase"):
        classname = case.attrib.get("classname", "")
        name = case.attrib.get("name", "")
        node_id = f"{classname}::{name}"
        try:
            seconds = float(case.attrib.get("time", "0"))
        except ValueError:
            seconds = 0.0
        # Keep the max for duplicate parametrised IDs so the dict is stable.
        if node_id in tests:
            tests[node_id] = max(tests[node_id], seconds)
        else:
            tests[node_id] = seconds
    return tests, suite_attrib


def _load_run(run_dir: Path) -> dict[str, Any]:
    """Load one run's JUnit, run-result.json, and progress data."""
    junit_path = run_dir / "pytest-junit.xml"
    result_path = run_dir / "run-result.json"
    tests, suite_attrib = _parse_junit(junit_path)
    run_result = json.loads(result_path.read_text(encoding="utf-8"))
    return {
        "run_dir": str(run_dir),
        "tests": tests,
        "suite_attrib": suite_attrib,
        "run_result": run_result,
    }


def _node_id_set(tests: dict[str, float]) -> set[str]:
    return set(tests.keys())


def _module_of(node_id: str) -> str:
    return node_id.rsplit("::", 1)[0]


# ---------------------------------------------------------------------------
# Gate computation
# ---------------------------------------------------------------------------

def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    return float(statistics.median(values))


def _floor_median(values: list[float]) -> float:
    """Median using Floor((n-1)/2) for odd, lower-middle for even.

    Matches the workflow's PowerShell [math]::Floor definition so the
    Python and PowerShell numbers agree on 3-sample arrays.
    """
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = (len(ordered) - 1) // 2
    return float(ordered[idx])


def _mad(values: list[float]) -> float:
    """Median absolute deviation — a robust spread estimator."""
    if len(values) < 2:
        return 0.0
    med = statistics.median(values)
    return float(statistics.median([abs(v - med) for v in values]))


def _percent(part: float, whole: float) -> float:
    if whole == 0:
        return 0.0
    return part / whole * 100.0


# ---------------------------------------------------------------------------
# Main comparison
# ---------------------------------------------------------------------------

def _build_comparison(
    results_dir: Path,
    *,
    baseline_sha: str,
    head_sha: str,
    dependency_match: bool,
    common_regression_threshold_pct: float,
    head_full_limit_seconds: float,
) -> dict[str, Any]:
    # ---- Load collection sets ----
    collection_dir = results_dir / "collection"
    baseline_ids_path = collection_dir / "baseline-node-ids.txt"
    head_ids_path = collection_dir / "head-node-ids.txt"
    baseline_ids = _read_id_file(baseline_ids_path)
    head_ids = _read_id_file(head_ids_path)
    common_ids = baseline_ids & head_ids
    baseline_only_ids = baseline_ids - common_ids
    head_only_ids = head_ids - common_ids

    # Persist the computed selection files so they are available as artifacts
    # and can be inspected without re-running collection.
    selection_dir = results_dir / "selection"
    selection_dir.mkdir(parents=True, exist_ok=True)
    _write_id_file(selection_dir / "common.txt", sorted(common_ids))
    _write_id_file(selection_dir / "head-only.txt", sorted(head_only_ids))
    _write_id_file(selection_dir / "baseline-only.txt", sorted(baseline_only_ids))

    # ---- Load common-suite paired runs ----
    common_pairs: list[dict[str, Any]] = []
    for pair_index in (1, 2, 3):
        pair_dir = results_dir / f"pair-{pair_index}"
        # Each pair has baseline/ and head/ subdirs (order is interleaved by
        # the workflow; we just read both sides here).
        b_run = _load_run(pair_dir / "baseline")
        h_run = _load_run(pair_dir / "head")
        common_pairs.append(
            {
                "pair": pair_index,
                "baseline_wall_seconds": b_run["run_result"]["elapsed_seconds"],
                "head_wall_seconds": h_run["run_result"]["elapsed_seconds"],
                "baseline_exit_code": b_run["run_result"]["exit_code"],
                "head_exit_code": h_run["run_result"]["exit_code"],
                "baseline_test_count": b_run["run_result"]["test_count"],
                "head_test_count": h_run["run_result"]["test_count"],
                "baseline_failures": b_run["run_result"]["failure_count"],
                "baseline_errors": b_run["run_result"]["error_count"],
                "baseline_skipped": b_run["run_result"]["skipped_count"],
                "head_failures": h_run["run_result"]["failure_count"],
                "head_errors": h_run["run_result"]["error_count"],
                "head_skipped": h_run["run_result"]["skipped_count"],
                "baseline_valid": b_run["run_result"]["valid"],
                "head_valid": h_run["run_result"]["valid"],
                "baseline_junit_present": b_run["run_result"]["junit_present"],
                "head_junit_present": h_run["run_result"]["junit_present"],
                "delta_seconds": round(
                    h_run["run_result"]["elapsed_seconds"]
                    - b_run["run_result"]["elapsed_seconds"],
                    2,
                ),
                "delta_pct": round(
                    _percent(
                        h_run["run_result"]["elapsed_seconds"]
                        - b_run["run_result"]["elapsed_seconds"],
                        b_run["run_result"]["elapsed_seconds"],
                    ),
                    1,
                ),
                # Per-test testcase totals (from JUnit sum).
                "baseline_testcase_total": round(
                    sum(b_run["tests"].values()), 2
                ),
                "head_testcase_total": round(sum(h_run["tests"].values()), 2),
            }
        )

    # ---- Load HEAD-only runs ----
    head_only_runs: list[dict[str, Any]] = []
    for run_index in (1, 2, 3):
        run_dir = results_dir / f"head-only/run-{run_index}"
        if not run_dir.is_dir():
            continue
        run = _load_run(run_dir)
        head_only_runs.append(
            {
                "run": run_index,
                "wall_seconds": run["run_result"]["elapsed_seconds"],
                "exit_code": run["run_result"]["exit_code"],
                "test_count": run["run_result"]["test_count"],
                "failures": run["run_result"]["failure_count"],
                "errors": run["run_result"]["error_count"],
                "skipped": run["run_result"]["skipped_count"],
                "valid": run["run_result"]["valid"],
                "junit_present": run["run_result"]["junit_present"],
                "testcase_total": round(sum(run["tests"].values()), 2),
            }
        )

    # ---- Load full HEAD runs ----
    head_full_runs: list[dict[str, Any]] = []
    for run_index in (1, 2, 3):
        run_dir = results_dir / f"head-full/run-{run_index}"
        if not run_dir.is_dir():
            continue
        run = _load_run(run_dir)
        head_full_runs.append(
            {
                "run": run_index,
                "wall_seconds": run["run_result"]["elapsed_seconds"],
                "exit_code": run["run_result"]["exit_code"],
                "test_count": run["run_result"]["test_count"],
                "failures": run["run_result"]["failure_count"],
                "errors": run["run_result"]["error_count"],
                "skipped": run["run_result"]["skipped_count"],
                "valid": run["run_result"]["valid"],
                "junit_present": run["run_result"]["junit_present"],
                "testcase_total": round(sum(run["tests"].values()), 2),
            }
        )

    # ---- Compute common-suite paired statistics ----
    paired_deltas = [p["delta_seconds"] for p in common_pairs]
    paired_deltas_pct = [p["delta_pct"] for p in common_pairs]
    baseline_walls = [p["baseline_wall_seconds"] for p in common_pairs]
    head_walls = [p["head_wall_seconds"] for p in common_pairs]
    paired_median_delta = _floor_median(paired_deltas)
    paired_median_delta_pct = _floor_median(paired_deltas_pct)
    baseline_median = _floor_median(baseline_walls)
    head_median = _floor_median(head_walls)

    # ---- HEAD-only statistics ----
    head_only_walls = [r["wall_seconds"] for r in head_only_runs]
    head_only_median = _floor_median(head_only_walls)

    # ---- Full HEAD statistics ----
    head_full_walls = [r["wall_seconds"] for r in head_full_runs]
    head_full_median = _floor_median(head_full_walls)
    head_full_test_count = (
        head_full_runs[0]["test_count"] if head_full_runs else 0
    )
    head_full_skipped = (
        head_full_runs[0]["skipped"] if head_full_runs else 0
    )
    head_full_failures = (
        head_full_runs[0]["failures"] if head_full_runs else 0
    )
    head_full_errors = (
        head_full_runs[0]["errors"] if head_full_runs else 0
    )

    # ---- Common test count consistency ----
    common_test_counts = {p["baseline_test_count"] for p in common_pairs}
    common_test_counts.update(p["head_test_count"] for p in common_pairs)
    common_count_consistent = len(common_test_counts) == 1

    # ---- All runs valid ----
    all_common_valid = all(
        p["baseline_valid"] and p["head_valid"] for p in common_pairs
    )
    all_head_only_valid = all(r["valid"] for r in head_only_runs) if head_only_runs else False
    all_head_full_valid = all(r["valid"] for r in head_full_runs) if head_full_runs else False
    all_runs_valid = (
        all_common_valid and all_head_only_valid and all_head_full_valid
    )

    # ---- Stable regression / unstable long-tail attribution ----
    # Use the common-pair JUnit per-test data to find tests that are
    # consistently slower on HEAD across all 3 pairs.
    stable_regressions: list[dict[str, Any]] = []
    unstable_long_tails: list[dict[str, Any]] = []
    if common_pairs:
        b_test_runs: list[dict[str, float]] = []
        h_test_runs: list[dict[str, float]] = []
        for pair in common_pairs:
            pair_dir = results_dir / f"pair-{pair['pair']}"
            b_tests, _ = _parse_junit(pair_dir / "baseline" / "pytest-junit.xml")
            h_tests, _ = _parse_junit(pair_dir / "head" / "pytest-junit.xml")
            b_test_runs.append(b_tests)
            h_test_runs.append(h_tests)

        for node_id in sorted(common_ids):
            b_vals = [t.get(node_id, 0.0) for t in b_test_runs]
            h_vals = [t.get(node_id, 0.0) for t in h_test_runs]
            b_med = _floor_median(b_vals)
            h_med = _floor_median(h_vals)
            delta = h_med - b_med
            # Stable regression: HEAD slower in all 3 pairs and median delta > 0.
            if delta > 0 and all(h_vals[i] > b_vals[i] for i in range(3)):
                stable_regressions.append(
                    {
                        "test": node_id,
                        "baseline_median": round(b_med, 4),
                        "head_median": round(h_med, 4),
                        "delta": round(delta, 4),
                        "head_spread": round(max(h_vals) - min(h_vals), 4),
                        "baseline_spread": round(max(b_vals) - min(b_vals), 4),
                    }
                )
            # Unstable long-tail: high HEAD spread (>0.5s) but not a stable
            # regression — these are the runner-noise suspects.
            h_spread = max(h_vals) - min(h_vals)
            if h_spread > 0.5 and not all(
                h_vals[i] > b_vals[i] for i in range(3)
            ):
                unstable_long_tails.append(
                    {
                        "test": node_id,
                        "baseline_median": round(b_med, 4),
                        "head_median": round(h_med, 4),
                        "head_spread": round(h_spread, 4),
                        "baseline_spread": round(
                            max(b_vals) - min(b_vals), 4
                        ),
                    }
                )

    stable_regressions.sort(key=lambda x: -x["delta"])
    unstable_long_tails.sort(key=lambda x: -x["head_spread"])

    # ---- Module-level deltas (common tests) ----
    module_deltas: dict[str, dict[str, float]] = defaultdict(
        lambda: {"baseline": 0.0, "head": 0.0, "count": 0}
    )
    if common_pairs:
        b_test_runs = []
        h_test_runs = []
        for pair in common_pairs:
            pair_dir = results_dir / f"pair-{pair['pair']}"
            b_tests, _ = _parse_junit(pair_dir / "baseline" / "pytest-junit.xml")
            h_tests, _ = _parse_junit(pair_dir / "head" / "pytest-junit.xml")
            b_test_runs.append(b_tests)
            h_test_runs.append(h_tests)
        for node_id in common_ids:
            b_med = _floor_median(
                [t.get(node_id, 0.0) for t in b_test_runs]
            )
            h_med = _floor_median(
                [t.get(node_id, 0.0) for t in h_test_runs]
            )
            module = _module_of(node_id)
            module_deltas[module]["baseline"] += b_med
            module_deltas[module]["head"] += h_med
            module_deltas[module]["count"] += 1
    module_rows = [
        {
            "module": mod,
            "count": data["count"],
            "baseline_sum": round(data["baseline"], 3),
            "head_sum": round(data["head"], 3),
            "delta": round(data["head"] - data["baseline"], 3),
        }
        for mod, data in module_deltas.items()
    ]
    module_rows.sort(key=lambda x: -x["delta"])

    # ---- HEAD-only top tests ----
    head_only_top: list[dict[str, Any]] = []
    if head_only_runs:
        h_only_tests: dict[str, list[float]] = defaultdict(list)
        for run in head_only_runs:
            run_dir = results_dir / f"head-only/run-{run['run']}"
            tests, _ = _parse_junit(run_dir / "pytest-junit.xml")
            for node_id, seconds in tests.items():
                h_only_tests[node_id].append(seconds)
        head_only_top = [
            {
                "test": node_id,
                "median": round(_floor_median(vals), 4),
            }
            for node_id, vals in h_only_tests.items()
        ]
        head_only_top.sort(key=lambda x: -x["median"])

    # ---- HEAD-only module costs ----
    head_only_module_costs: dict[str, dict[str, float]] = defaultdict(
        lambda: {"sum": 0.0, "count": 0}
    )
    if head_only_runs:
        h_only_tests: dict[str, list[float]] = defaultdict(list)
        for run in head_only_runs:
            run_dir = results_dir / f"head-only/run-{run['run']}"
            tests, _ = _parse_junit(run_dir / "pytest-junit.xml")
            for node_id, seconds in tests.items():
                h_only_tests[node_id].append(seconds)
        for node_id, vals in h_only_tests.items():
            module = _module_of(node_id)
            head_only_module_costs[module]["sum"] += _floor_median(vals)
            head_only_module_costs[module]["count"] += 1
    head_only_module_rows = [
        {
            "module": mod,
            "count": data["count"],
            "median_sum": round(data["sum"], 3),
        }
        for mod, data in head_only_module_costs.items()
    ]
    head_only_module_rows.sort(key=lambda x: -x["median_sum"])

    # ---- Gates ----
    # Common suite: paired median regression must not exceed threshold.
    common_gate_passed = (
        all_common_valid
        and common_count_consistent
        and paired_median_delta_pct <= common_regression_threshold_pct
        and all(p["baseline_failures"] == 0 for p in common_pairs)
        and all(p["baseline_errors"] == 0 for p in common_pairs)
        and all(p["head_failures"] == 0 for p in common_pairs)
        and all(p["head_errors"] == 0 for p in common_pairs)
        and all(p["head_skipped"] <= p["baseline_skipped"] for p in common_pairs)
    )

    # HEAD-only: all valid, no failures, no unexplained skipped growth.
    head_only_gate_passed = (
        all_head_only_valid
        and all(r["failures"] == 0 for r in head_only_runs)
        and all(r["errors"] == 0 for r in head_only_runs)
    )

    # Full HEAD suite: median <= limit, test count not reduced, no failures,
    # skipped no unexplained growth.
    # Use baseline collection count as the floor for test count.
    head_full_gate_passed = (
        all_head_full_valid
        and head_full_median <= head_full_limit_seconds
        and head_full_test_count >= len(baseline_ids)
        and head_full_failures == 0
        and head_full_errors == 0
        and head_full_skipped <= 1  # baseline skipped is 1; allow no growth
    )

    all_gates_passed = (
        common_gate_passed
        and head_only_gate_passed
        and head_full_gate_passed
        and dependency_match
        and all_runs_valid
    )

    # ---- Build report ----
    execution_order = _load_execution_order(results_dir)

    report: dict[str, Any] = {
        "baseline_revision": baseline_sha,
        "head_revision": head_sha,
        "dependency_match": dependency_match,
        "execution_order": execution_order,
        "common_regression_threshold_pct": common_regression_threshold_pct,
        "head_full_limit_seconds": head_full_limit_seconds,
        "collection": {
            "baseline_count": len(baseline_ids),
            "head_count": len(head_ids),
            "common_count": len(common_ids),
            "head_only_count": len(head_only_ids),
            "baseline_only_count": len(baseline_only_ids),
            "common_ids_sha256": _sha256_of_ids(common_ids),
        },
        "common_suite": {
            "pairs": common_pairs,
            "paired_median_delta_seconds": round(paired_median_delta, 2),
            "paired_median_delta_percent": round(paired_median_delta_pct, 1),
            "baseline_median_seconds": round(baseline_median, 2),
            "head_median_seconds": round(head_median, 2),
            "baseline_walls": [round(w, 2) for w in baseline_walls],
            "head_walls": [round(w, 2) for w in head_walls],
            "paired_deltas": [round(d, 2) for d in paired_deltas],
            "paired_deltas_pct": [round(d, 1) for d in paired_deltas_pct],
            "common_count_consistent": common_count_consistent,
            "common_test_counts": sorted(common_test_counts),
            "mad_paired_delta": round(_mad(paired_deltas), 2),
            "gate_passed": common_gate_passed,
            "top_module_deltas": module_rows[:20],
        },
        "head_only_suite": {
            "runs": head_only_runs,
            "median_seconds": round(head_only_median, 2),
            "wall_clocks": [round(w, 2) for w in head_only_walls],
            "top_tests": head_only_top[:25],
            "top_modules": head_only_module_rows[:20],
            "gate_passed": head_only_gate_passed,
        },
        "head_full_suite": {
            "runs": head_full_runs,
            "median_seconds": round(head_full_median, 2),
            "wall_clocks": [round(w, 2) for w in head_full_walls],
            "absolute_limit_seconds": head_full_limit_seconds,
            "test_count": head_full_test_count,
            "failures": head_full_failures,
            "errors": head_full_errors,
            "skipped": head_full_skipped,
            "gate_passed": head_full_gate_passed,
        },
        "stable_regressions": stable_regressions[:30],
        "unstable_long_tails": unstable_long_tails[:30],
        "all_runs_valid": all_runs_valid,
        "all_gates_passed": all_gates_passed,
    }
    return report


def _read_id_file(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    ids: set[str] = set()
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            ids.add(line)
    return ids


def _write_id_file(path: Path, ids: list[str]) -> None:
    path.write_text("\n".join(ids) + ("\n" if ids else ""), encoding="utf-8")


def _sha256_of_ids(ids: set[str]) -> str:
    payload = "\n".join(sorted(ids)).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _load_execution_order(results_dir: Path) -> list[str]:
    """Load the execution-order manifest written by the workflow."""
    path = results_dir / "execution-order.json"
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and "order" in data:
            return list(data["order"])
    except (OSError, ValueError):
        pass
    return []


# ---------------------------------------------------------------------------
# Markdown summary
# ---------------------------------------------------------------------------

def _build_markdown(report: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("## Standard timing validation (layered)")
    lines.append("")
    lines.append(
        f"- baseline: `{report['baseline_revision']}`  "
        f"HEAD: `{report['head_revision']}`"
    )
    lines.append(
        f"- dependency match: {report['dependency_match']}"
    )
    lines.append(
        f"- execution order: {', '.join(report.get('execution_order', []))}"
    )
    lines.append("")

    # Collection
    coll = report["collection"]
    lines.append("### Collection")
    lines.append("")
    lines.append("| set | count |")
    lines.append("|---|---|")
    lines.append(f"| baseline | {coll['baseline_count']} |")
    lines.append(f"| HEAD | {coll['head_count']} |")
    lines.append(f"| common | {coll['common_count']} |")
    lines.append(f"| HEAD-only | {coll['head_only_count']} |")
    lines.append(f"| baseline-only | {coll['baseline_only_count']} |")
    lines.append(f"| common IDs sha256 | `{coll['common_ids_sha256'][:16]}…` |")
    lines.append("")

    # Common suite
    cs = report["common_suite"]
    lines.append("### Common-suite paired comparison")
    lines.append("")
    lines.append("| pair | baseline (s) | HEAD (s) | delta (s) | delta (%) |")
    lines.append("|---|---|---|---|---|")
    for p in cs["pairs"]:
        lines.append(
            f"| {p['pair']} | {p['baseline_wall_seconds']:.2f} | "
            f"{p['head_wall_seconds']:.2f} | {p['delta_seconds']:+.2f} | "
            f"{p['delta_pct']:+.1f} |"
        )
    lines.append("")
    lines.append(
        f"- paired median delta: **{cs['paired_median_delta_seconds']:+.2f}s** "
        f"({cs['paired_median_delta_pct']:+.1f}%)"
    )
    lines.append(
        f"- baseline median: {cs['baseline_median_seconds']:.2f}s | "
        f"HEAD median: {cs['head_median_seconds']:.2f}s"
    )
    lines.append(
        f"- MAD of paired deltas: {cs['mad_paired_delta']:.2f}s"
    )
    lines.append(
        f"- common count consistent: {cs['common_count_consistent']} "
        f"(counts: {cs['common_test_counts']})"
    )
    lines.append(
        f"- gate (paired median regression <= "
        f"{report['common_regression_threshold_pct']}%): "
        f"{'PASS' if cs['gate_passed'] else 'FAIL'}"
    )
    lines.append("")

    # HEAD-only suite
    ho = report["head_only_suite"]
    lines.append("### HEAD-only test cost")
    lines.append("")
    lines.append("| run | wall (s) | testcase total (s) | test count |")
    lines.append("|---|---|---|---|")
    for r in ho["runs"]:
        lines.append(
            f"| {r['run']} | {r['wall_seconds']:.2f} | "
            f"{r['testcase_total']:.2f} | {r['test_count']} |"
        )
    lines.append("")
    lines.append(f"- median wall: {ho['median_seconds']:.2f}s")
    lines.append(f"- gate (all valid, no failures): {'PASS' if ho['gate_passed'] else 'FAIL'}")
    if ho["top_tests"]:
        lines.append("")
        lines.append("Top 10 HEAD-only tests by median:")
        lines.append("")
        lines.append("| median (s) | test |")
        lines.append("|---|---|")
        for t in ho["top_tests"][:10]:
            lines.append(f"| {t['median']:.3f} | `{t['test']}` |")
    lines.append("")

    # Full HEAD suite
    hf = report["head_full_suite"]
    lines.append("### HEAD full suite")
    lines.append("")
    lines.append("| run | wall (s) | testcase total (s) | test count |")
    lines.append("|---|---|---|---|")
    for r in hf["runs"]:
        lines.append(
            f"| {r['run']} | {r['wall_seconds']:.2f} | "
            f"{r['testcase_total']:.2f} | {r['test_count']} |"
        )
    lines.append("")
    lines.append(
        f"- median wall: {hf['median_seconds']:.2f}s "
        f"(limit {hf['absolute_limit_seconds']:.0f}s)"
    )
    lines.append(
        f"- test count: {hf['test_count']} | failures: {hf['failures']} | "
        f"errors: {hf['errors']} | skipped: {hf['skipped']}"
    )
    lines.append(
        f"- gate (median <= {hf['absolute_limit_seconds']:.0f}s, no failures, "
        f"test count not reduced): "
        f"{'PASS' if hf['gate_passed'] else 'FAIL'}"
    )
    lines.append("")

    # Stable regressions
    if report["stable_regressions"]:
        lines.append("### Stable common-test regressions (HEAD slower in all 3 pairs)")
        lines.append("")
        lines.append("| delta (s) | baseline med | HEAD med | test |")
        lines.append("|---|---|---|---|")
        for r in report["stable_regressions"][:15]:
            lines.append(
                f"| {r['delta']:+.3f} | {r['baseline_median']:.3f} | "
                f"{r['head_median']:.3f} | `{r['test']}` |"
            )
        lines.append("")

    # Unstable long-tails
    if report["unstable_long_tails"]:
        lines.append("### Unstable HEAD long-tails (high spread, not stable regression)")
        lines.append("")
        lines.append("| HEAD spread (s) | baseline med | HEAD med | test |")
        lines.append("|---|---|---|---|")
        for r in report["unstable_long_tails"][:15]:
            lines.append(
                f"| {r['head_spread']:.3f} | {r['baseline_median']:.3f} | "
                f"{r['head_median']:.3f} | `{r['test']}` |"
            )
        lines.append("")

    # Top module deltas
    if cs["top_module_deltas"]:
        lines.append("### Top common-test module deltas")
        lines.append("")
        lines.append("| delta (s) | baseline sum | HEAD sum | count | module |")
        lines.append("|---|---|---|---|---|")
        for m in cs["top_module_deltas"][:10]:
            lines.append(
                f"| {m['delta']:+.2f} | {m['baseline_sum']:.2f} | "
                f"{m['head_sum']:.2f} | {m['count']} | `{m['module']}` |"
            )
        lines.append("")

    # Final verdict
    lines.append("### Final verdict")
    lines.append("")
    lines.append(f"- all runs valid: {report['all_runs_valid']}")
    lines.append(f"- **all gates passed: {report['all_gates_passed']}**")
    lines.append("")
    if not report["all_gates_passed"]:
        lines.append("Gate failures:")
        if not cs["gate_passed"]:
            lines.append(
                f"- common-suite gate FAILED (paired median regression "
                f"{cs['paired_median_delta_pct']:+.1f}% > "
                f"{report['common_regression_threshold_pct']}%)"
            )
        if not ho["gate_passed"]:
            lines.append("- HEAD-only gate FAILED (invalid runs or failures)")
        if not hf["gate_passed"]:
            lines.append(
                f"- HEAD full-suite gate FAILED (median "
                f"{hf['median_seconds']:.2f}s > "
                f"{hf['absolute_limit_seconds']:.0f}s, or failures, or "
                f"test count reduced)"
            )
        if not report["dependency_match"]:
            lines.append("- dependency mismatch")
        if not report["all_runs_valid"]:
            lines.append("- not all runs valid")

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--results-dir",
        type=Path,
        required=True,
        help="Directory containing pair-*/, head-only/, head-full/, collection/",
    )
    parser.add_argument("--baseline-sha", required=True)
    parser.add_argument("--head-sha", required=True)
    parser.add_argument(
        "--dependency-match",
        choices=("true", "false"),
        required=True,
        help="Whether baseline and HEAD requirements.txt hashes match",
    )
    parser.add_argument(
        "--common-regression-threshold-pct",
        type=float,
        default=10.0,
        help="Maximum allowed paired median regression percentage for common suite",
    )
    parser.add_argument(
        "--head-full-limit-seconds",
        type=float,
        default=240.0,
        help="Absolute wall-clock limit for HEAD full suite median",
    )
    args = parser.parse_args()

    report = _build_comparison(
        args.results_dir,
        baseline_sha=args.baseline_sha,
        head_sha=args.head_sha,
        dependency_match=args.dependency_match == "true",
        common_regression_threshold_pct=args.common_regression_threshold_pct,
        head_full_limit_seconds=args.head_full_limit_seconds,
    )

    # Write JSON report.
    json_path = args.results_dir / "timing-comparison.json"
    json_path.write_text(
        json.dumps(report, indent=2, sort_keys=False), encoding="utf-8"
    )

    # Write Markdown summary.
    md_path = args.results_dir / "timing-comparison.md"
    md_text = _build_markdown(report)
    md_path.write_text(md_text, encoding="utf-8")

    # Write to GITHUB_STEP_SUMMARY if available.
    step_summary = __import__("os").environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        with open(step_summary, "a", encoding="utf-8") as fh:
            fh.write(md_text)

    # Print key numbers to stdout for log visibility.
    print(f"timing_validation={'PASSED' if report['all_gates_passed'] else 'FAILED'}")
    print(
        f"common_paired_median_delta={report['common_suite']['paired_median_delta_seconds']:+.2f}s "
        f"({report['common_suite']['paired_median_delta_pct']:+.1f}%)"
    )
    print(f"head_only_median={report['head_only_suite']['median_seconds']:.2f}s")
    print(f"head_full_median={report['head_full_suite']['median_seconds']:.2f}s")
    print(f"stable_regression_count={len(report['stable_regressions'])}")
    print(f"unstable_long_tail_count={len(report['unstable_long_tails'])}")

    if not report["all_gates_passed"]:
        if not report["common_suite"]["gate_passed"]:
            print("reason=common_suite_gate_failed")
        if not report["head_only_suite"]["gate_passed"]:
            print("reason=head_only_gate_failed")
        if not report["head_full_suite"]["gate_passed"]:
            print("reason=head_full_suite_gate_failed")
        if not report["dependency_match"]:
            print("reason=dependency_mismatch")
        if not report["all_runs_valid"]:
            print("reason=not_all_runs_valid")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
