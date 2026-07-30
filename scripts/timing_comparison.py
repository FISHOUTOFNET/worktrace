#!/usr/bin/env python3
"""Standard timing validation: selection prepare + paired comparison.

Two explicit modes, invoked at different workflow stages:

* ``--write-selection-only`` (prepare): reads the baseline and HEAD
  collection files, computes the common / HEAD-only / baseline-only
  node-ID sets, validates set consistency, and writes the selection
  files plus a manifest.  Does NOT read any timing or JUnit results.
  Exits 0 on success, non-zero on validation failure.

* ``--compare`` (compare): reads the per-run ``timing.json`` produced
  by the HEAD-owned ``pytest_timing_plugin`` plus the wall-clock
  ``run-result.json`` from each pair / HEAD-only / HEAD-full directory,
  validates schema/SHA/selection-hash/test-count consistency, computes
  the layered gates, and writes ``timing-comparison.json`` +
  ``timing-comparison.md``.  Exits 0 if all gates pass, non-zero
  otherwise.

Per-test attribution uses the exact pytest ``report.nodeid`` recorded
by the timing plugin — it never infers node IDs from JUnit
classname/name pairs, which are ambiguous for parametrised tests.

Exit codes
----------
* 0 — success (all gates passed for compare, selection written for prepare)
* 2 — input/schema error (missing file, schema mismatch, SHA mismatch)
* 3 — execution incomplete (missing run, failed run, test-count mismatch)
* 4 — performance gate failure (regression exceeds threshold or limit)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

_SCHEMA_VERSION = 1
_EXIT_INPUT_SCHEMA = 2
_EXIT_INCOMPLETE = 3
_EXIT_GATE_FAILED = 4


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

class ValidationError(Exception):
    """Raised when an input file or schema check fails (exit code 2)."""


class IncompleteRunError(Exception):
    """Raised when a run is missing, failed, or has mismatched counts (exit 3)."""


class GateFailure(Exception):
    """Raised when a performance gate fails (exit 4)."""


def _read_id_file(path: Path) -> set[str]:
    if not path.is_file():
        raise ValidationError(f"collection file missing: {path}")
    ids: set[str] = set()
    duplicates: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line in ids:
            duplicates.append(line)
        ids.add(line)
    if duplicates:
        sample = duplicates[:5]
        raise ValidationError(
            f"duplicate node IDs in {path}: {sample}"
        )
    return ids


def _write_id_file(path: Path, ids: list[str]) -> None:
    """Atomic write of a node-ID selection file."""
    content = "\n".join(ids) + ("\n" if ids else "")
    _atomic_write_text(path, content)


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    text = json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=False) + "\n"
    _atomic_write_text(path, text)


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _sha256_of_ids(ids: set[str]) -> str:
    payload = "\n".join(sorted(ids)).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _sha256_of_file(path: Path) -> str:
    if not path.is_file():
        return ""
    return hashlib.sha256(path.read_bytes()).hexdigest()


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
    if len(values) < 2:
        return 0.0
    med = statistics.median(values)
    return float(statistics.median([abs(v - med) for v in values]))


def _percent(part: float, whole: float) -> float:
    if whole == 0:
        return 0.0
    return part / whole * 100.0


def _module_of(node_id: str) -> str:
    return node_id.rsplit("::", 1)[0]


# ---------------------------------------------------------------------------
# Prepare mode
# ---------------------------------------------------------------------------

def _run_prepare(args: argparse.Namespace) -> int:
    results_dir = args.results_dir
    collection_dir = results_dir / "collection"
    baseline_ids_path = collection_dir / "baseline-node-ids.txt"
    head_ids_path = collection_dir / "head-node-ids.txt"

    try:
        baseline_ids = _read_id_file(baseline_ids_path)
        head_ids = _read_id_file(head_ids_path)
    except ValidationError as exc:
        print(f"prepare_error: {exc}", file=sys.stderr)
        return _EXIT_INPUT_SCHEMA

    common_ids = baseline_ids & head_ids
    head_only_ids = head_ids - common_ids
    baseline_only_ids = baseline_ids - common_ids

    # ---- Set-consistency validation ----
    if not common_ids:
        print(
            "prepare_error: common set is empty — baseline and HEAD share "
            "no tests; collection likely failed",
            file=sys.stderr,
        )
        return _EXIT_INPUT_SCHEMA

    if common_ids | head_only_ids != head_ids:
        print(
            "prepare_error: common + head-only != HEAD collection "
            "(set consistency violated)",
            file=sys.stderr,
        )
        return _EXIT_INPUT_SCHEMA

    if common_ids | baseline_only_ids != baseline_ids:
        print(
            "prepare_error: common + baseline-only != baseline collection "
            "(set consistency violated)",
            file=sys.stderr,
        )
        return _EXIT_INPUT_SCHEMA

    # ---- Write selection files (atomic) ----
    selection_dir = results_dir / "selection"
    selection_dir.mkdir(parents=True, exist_ok=True)
    common_path = selection_dir / "common.txt"
    head_only_path = selection_dir / "head-only.txt"
    baseline_only_path = selection_dir / "baseline-only.txt"
    _write_id_file(common_path, sorted(common_ids))
    _write_id_file(head_only_path, sorted(head_only_ids))
    _write_id_file(baseline_only_path, sorted(baseline_only_ids))

    # ---- Write manifest (atomic) ----
    manifest = {
        "schema_version": _SCHEMA_VERSION,
        "baseline_sha": args.baseline_sha,
        "head_sha": args.head_sha,
        "dependency_match": args.dependency_match == "true",
        "baseline_collected": len(baseline_ids),
        "head_collected": len(head_ids),
        "common_count": len(common_ids),
        "head_only_count": len(head_only_ids),
        "baseline_only_count": len(baseline_only_ids),
        "common_selection_hash": _sha256_of_ids(common_ids),
        "head_only_selection_hash": _sha256_of_ids(head_only_ids),
        "common_selection_file_hash": _sha256_of_file(common_path),
        "head_only_selection_file_hash": _sha256_of_file(head_only_path),
    }
    manifest_path = selection_dir / "manifest.json"
    _write_json_atomic(manifest_path, manifest)

    print(f"prepare: common={len(common_ids)} head_only={len(head_only_ids)} "
          f"baseline_only={len(baseline_only_ids)}")
    print(f"prepare: manifest written to {manifest_path}")
    return 0


# ---------------------------------------------------------------------------
# Compare mode — load and validate per-run data
# ---------------------------------------------------------------------------

def _load_timing_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ValidationError(f"timing.json missing: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValidationError(f"cannot parse {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValidationError(f"{path}: root is not an object")
    if payload.get("schema_version") != _SCHEMA_VERSION:
        raise ValidationError(
            f"{path}: schema_version {payload.get('schema_version')} "
            f"!= expected {_SCHEMA_VERSION}"
        )
    return payload


def _load_run_result(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ValidationError(f"run-result.json missing: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValidationError(f"cannot parse {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValidationError(f"{path}: root is not an object")
    return payload


def _validate_timing_payload(
    payload: dict[str, Any],
    *,
    expected_revision: str,
    expected_selection_hash: str | None,
    expected_selected_count: int | None,
    label: str,
) -> None:
    """Validate a timing.json payload against expected metadata.

    ``expected_selection_hash`` is None when no selection was applied
    (full-suite runs).  ``expected_selected_count`` is None when not
    cross-checking against a manifest count.
    """
    revision = payload.get("revision", "")
    if revision != expected_revision:
        raise ValidationError(
            f"{label}: revision {revision!r} != expected {expected_revision!r}"
        )

    selection_hash = payload.get("selection_hash", "")
    if expected_selection_hash is not None:
        if selection_hash != expected_selection_hash:
            raise ValidationError(
                f"{label}: selection_hash {selection_hash!r} != "
                f"expected {expected_selection_hash!r}"
            )

    exit_code = int(payload.get("exit_code", -1))
    if exit_code != 0:
        raise IncompleteRunError(
            f"{label}: timing.json exit_code={exit_code} (run failed or interrupted)"
        )

    # No test should have outcome == "failed" — a failed run must not
    # contribute to performance samples.
    tests = payload.get("tests", [])
    failed = [t for t in tests if t.get("outcome") == "failed"]
    if failed:
        sample = [t["nodeid"] for t in failed[:3]]
        raise IncompleteRunError(
            f"{label}: {len(failed)} test(s) failed in timing.json; "
            f"first: {sample}"
        )

    if expected_selected_count is not None:
        selected = int(payload.get("selected_count", -1))
        if selected != expected_selected_count:
            raise IncompleteRunError(
                f"{label}: selected_count {selected} != "
                f"expected {expected_selected_count}"
            )


def _tests_map(payload: dict[str, Any]) -> dict[str, float]:
    """Map nodeid -> total_seconds from a timing.json payload."""
    return {
        t["nodeid"]: float(t.get("total_seconds", 0.0))
        for t in payload.get("tests", [])
        if isinstance(t, dict) and "nodeid" in t
    }


def _load_pair(
    results_dir: Path,
    pair_index: int,
    *,
    baseline_sha: str,
    head_sha: str,
    common_selection_hash: str,
    common_count: int,
) -> dict[str, Any]:
    pair_dir = results_dir / f"pair-{pair_index}"
    b_timing_path = pair_dir / "baseline" / "timing.json"
    h_timing_path = pair_dir / "head" / "timing.json"
    b_result_path = pair_dir / "baseline" / "run-result.json"
    h_result_path = pair_dir / "head" / "run-result.json"

    b_timing = _load_timing_json(b_timing_path)
    h_timing = _load_timing_json(h_timing_path)
    b_result = _load_run_result(b_result_path)
    h_result = _load_run_result(h_result_path)

    _validate_timing_payload(
        b_timing,
        expected_revision=baseline_sha,
        expected_selection_hash=common_selection_hash,
        expected_selected_count=common_count,
        label=f"pair-{pair_index}/baseline",
    )
    _validate_timing_payload(
        h_timing,
        expected_revision=head_sha,
        expected_selection_hash=common_selection_hash,
        expected_selected_count=common_count,
        label=f"pair-{pair_index}/head",
    )

    b_wall = float(b_result.get("elapsed_seconds", 0.0))
    h_wall = float(h_result.get("elapsed_seconds", 0.0))
    if b_wall <= 0 or h_wall <= 0:
        raise IncompleteRunError(
            f"pair-{pair_index}: wall-clock elapsed_seconds is zero or missing"
        )

    b_exit = int(b_result.get("exit_code", -1))
    h_exit = int(h_result.get("exit_code", -1))
    if b_exit != 0 or h_exit != 0:
        raise IncompleteRunError(
            f"pair-{pair_index}: run-result exit codes baseline={b_exit} "
            f"head={h_exit}"
        )

    b_failures = int(b_result.get("failure_count", 0)) + int(
        b_result.get("error_count", 0)
    )
    h_failures = int(h_result.get("failure_count", 0)) + int(
        h_result.get("error_count", 0)
    )
    if b_failures or h_failures:
        raise IncompleteRunError(
            f"pair-{pair_index}: failures/errors baseline={b_failures} "
            f"head={h_failures}"
        )

    return {
        "pair": pair_index,
        "baseline_wall_seconds": b_wall,
        "head_wall_seconds": h_wall,
        "baseline_exit_code": b_exit,
        "head_exit_code": h_exit,
        "baseline_test_count": int(b_result.get("test_count", 0)),
        "head_test_count": int(h_result.get("test_count", 0)),
        "baseline_failures": int(b_result.get("failure_count", 0)),
        "baseline_errors": int(b_result.get("error_count", 0)),
        "baseline_skipped": int(b_result.get("skipped_count", 0)),
        "head_failures": int(h_result.get("failure_count", 0)),
        "head_errors": int(h_result.get("error_count", 0)),
        "head_skipped": int(h_result.get("skipped_count", 0)),
        "baseline_valid": bool(b_result.get("valid", False)),
        "head_valid": bool(h_result.get("valid", False)),
        "delta_seconds": round(h_wall - b_wall, 2),
        "delta_pct": round(_percent(h_wall - b_wall, b_wall), 1),
        "baseline_testcase_total": round(
            sum(_tests_map(b_timing).values()), 2
        ),
        "head_testcase_total": round(sum(_tests_map(h_timing).values()), 2),
        "_baseline_tests": _tests_map(b_timing),
        "_head_tests": _tests_map(h_timing),
    }


def _load_simple_run(
    run_dir: Path,
    *,
    expected_revision: str,
    expected_selection_hash: str | None,
    expected_selected_count: int | None,
    label: str,
) -> dict[str, Any]:
    timing = _load_timing_json(run_dir / "timing.json")
    result = _load_run_result(run_dir / "run-result.json")
    _validate_timing_payload(
        timing,
        expected_revision=expected_revision,
        expected_selection_hash=expected_selection_hash,
        expected_selected_count=expected_selected_count,
        label=label,
    )
    wall = float(result.get("elapsed_seconds", 0.0))
    if wall <= 0:
        raise IncompleteRunError(f"{label}: wall-clock elapsed_seconds is zero")
    exit_code = int(result.get("exit_code", -1))
    if exit_code != 0:
        raise IncompleteRunError(f"{label}: run-result exit_code={exit_code}")
    failures = int(result.get("failure_count", 0)) + int(
        result.get("error_count", 0)
    )
    if failures:
        raise IncompleteRunError(f"{label}: {failures} failures/errors")
    return {
        "wall_seconds": wall,
        "exit_code": exit_code,
        "test_count": int(result.get("test_count", 0)),
        "failures": int(result.get("failure_count", 0)),
        "errors": int(result.get("error_count", 0)),
        "skipped": int(result.get("skipped_count", 0)),
        "valid": bool(result.get("valid", False)),
        "testcase_total": round(sum(_tests_map(timing).values()), 2),
        "_tests": _tests_map(timing),
    }


# ---------------------------------------------------------------------------
# Compare mode — gate computation
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
    # ---- Load manifest ----
    manifest_path = results_dir / "selection" / "manifest.json"
    if not manifest_path.is_file():
        raise ValidationError(f"manifest missing: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != _SCHEMA_VERSION:
        raise ValidationError(
            f"manifest schema_version {manifest.get('schema_version')} "
            f"!= expected {_SCHEMA_VERSION}"
        )
    if manifest.get("baseline_sha") != baseline_sha:
        raise ValidationError(
            f"manifest baseline_sha {manifest.get('baseline_sha')!r} "
            f"!= expected {baseline_sha!r}"
        )
    if manifest.get("head_sha") != head_sha:
        raise ValidationError(
            f"manifest head_sha {manifest.get('head_sha')!r} "
            f"!= expected {head_sha!r}"
        )

    common_count = int(manifest["common_count"])
    head_only_count = int(manifest["head_only_count"])
    # Use the file hash (not the sorted-IDs hash) because the timing plugin
    # computes ``hashlib.sha256(file_bytes)`` at runtime.  The sorted-IDs
    # hash is a separate field used for manifest integrity, but the
    # cross-check against the timing JSON must use the same definition.
    common_hash = manifest["common_selection_file_hash"]
    head_only_hash = manifest["head_only_selection_file_hash"]
    baseline_collected = int(manifest["baseline_collected"])

    # ---- Load common-suite pairs ----
    common_pairs: list[dict[str, Any]] = []
    for pair_index in (1, 2, 3):
        pair = _load_pair(
            results_dir,
            pair_index,
            baseline_sha=baseline_sha,
            head_sha=head_sha,
            common_selection_hash=common_hash,
            common_count=common_count,
        )
        common_pairs.append(pair)

    # ---- Load HEAD-only runs ----
    # If head_only_count is 0, there are no HEAD-only tests and the workflow
    # skips the head-only runs (an empty selection file fails-closed in the
    # selection plugin).  The gate is vacuously passed.
    head_only_runs: list[dict[str, Any]] = []
    if head_only_count > 0:
        for run_index in (1, 2, 3):
            run_dir = results_dir / f"head-only/run-{run_index}"
            run = _load_simple_run(
                run_dir,
                expected_revision=head_sha,
                expected_selection_hash=head_only_hash,
                expected_selected_count=head_only_count,
                label=f"head-only/run-{run_index}",
            )
            run["run"] = run_index
            head_only_runs.append(run)

    # ---- Load full HEAD runs ----
    head_full_runs: list[dict[str, Any]] = []
    for run_index in (1, 2, 3):
        run_dir = results_dir / f"head-full/run-{run_index}"
        run = _load_simple_run(
            run_dir,
            expected_revision=head_sha,
            expected_selection_hash="",  # full suite: no selection
            expected_selected_count=None,
            label=f"head-full/run-{run_index}",
        )
        run["run"] = run_index
        head_full_runs.append(run)

    # ---- Common-suite paired statistics ----
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
    head_full_test_count = head_full_runs[0]["test_count"] if head_full_runs else 0
    head_full_skipped = head_full_runs[0]["skipped"] if head_full_runs else 0
    head_full_failures = head_full_runs[0]["failures"] if head_full_runs else 0
    head_full_errors = head_full_runs[0]["errors"] if head_full_runs else 0

    # ---- Common test count consistency ----
    common_test_counts = {p["baseline_test_count"] for p in common_pairs}
    common_test_counts.update(p["head_test_count"] for p in common_pairs)
    common_count_consistent = len(common_test_counts) == 1

    # ---- All runs valid ----
    all_common_valid = all(
        p["baseline_valid"] and p["head_valid"] for p in common_pairs
    )
    # When head_only_count == 0, there are no head-only runs; vacuously valid.
    all_head_only_valid = all(r["valid"] for r in head_only_runs) if head_only_runs else True
    all_head_full_valid = all(r["valid"] for r in head_full_runs)
    all_runs_valid = all_common_valid and all_head_only_valid and all_head_full_valid

    # ---- Stable regression / unstable long-tail attribution ----
    stable_regressions: list[dict[str, Any]] = []
    unstable_long_tails: list[dict[str, Any]] = []
    common_ids = set(common_pairs[0]["_baseline_tests"].keys())
    for pair in common_pairs[1:]:
        common_ids &= set(pair["_baseline_tests"].keys())
    for pair in common_pairs:
        common_ids &= set(pair["_head_tests"].keys())

    b_test_runs = [p["_baseline_tests"] for p in common_pairs]
    h_test_runs = [p["_head_tests"] for p in common_pairs]
    for node_id in sorted(common_ids):
        b_vals = [t.get(node_id, 0.0) for t in b_test_runs]
        h_vals = [t.get(node_id, 0.0) for t in h_test_runs]
        b_med = _floor_median(b_vals)
        h_med = _floor_median(h_vals)
        delta = h_med - b_med
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
                    "baseline_spread": round(max(b_vals) - min(b_vals), 4),
                }
            )
    stable_regressions.sort(key=lambda x: -x["delta"])
    unstable_long_tails.sort(key=lambda x: -x["head_spread"])

    # ---- Module-level deltas (common tests) ----
    module_deltas: dict[str, dict[str, float]] = defaultdict(
        lambda: {"baseline": 0.0, "head": 0.0, "count": 0}
    )
    for node_id in common_ids:
        b_med = _floor_median([t.get(node_id, 0.0) for t in b_test_runs])
        h_med = _floor_median([t.get(node_id, 0.0) for t in h_test_runs])
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
            for node_id, seconds in run["_tests"].items():
                h_only_tests[node_id].append(seconds)
        head_only_top = [
            {"test": node_id, "median": round(_floor_median(vals), 4)}
            for node_id, vals in h_only_tests.items()
        ]
        head_only_top.sort(key=lambda x: -x["median"])

    # ---- HEAD-only module costs ----
    head_only_module_costs: dict[str, dict[str, float]] = defaultdict(
        lambda: {"sum": 0.0, "count": 0}
    )
    if head_only_runs:
        h_only_tests_m: dict[str, list[float]] = defaultdict(list)
        for run in head_only_runs:
            for node_id, seconds in run["_tests"].items():
                h_only_tests_m[node_id].append(seconds)
        for node_id, vals in h_only_tests_m.items():
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

    head_only_gate_passed = (
        all_head_only_valid
        and all(r["failures"] == 0 for r in head_only_runs)
        and all(r["errors"] == 0 for r in head_only_runs)
    )

    head_full_gate_passed = (
        all_head_full_valid
        and head_full_median <= head_full_limit_seconds
        and head_full_test_count >= baseline_collected
        and head_full_failures == 0
        and head_full_errors == 0
    )

    all_gates_passed = (
        common_gate_passed
        and head_only_gate_passed
        and head_full_gate_passed
        and dependency_match
        and all_runs_valid
    )

    # ---- Strip private fields before reporting ----
    for p in common_pairs:
        p.pop("_baseline_tests", None)
        p.pop("_head_tests", None)
    for r in head_only_runs:
        r.pop("_tests", None)
    for r in head_full_runs:
        r.pop("_tests", None)

    # ---- Load execution order ----
    execution_order: list[str] = []
    order_path = results_dir / "execution-order.json"
    if order_path.is_file():
        try:
            data = json.loads(order_path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                execution_order = data
        except (OSError, ValueError):
            pass

    return {
        "baseline_revision": baseline_sha,
        "head_revision": head_sha,
        "dependency_match": dependency_match,
        "execution_order": execution_order,
        "common_regression_threshold_pct": common_regression_threshold_pct,
        "head_full_limit_seconds": head_full_limit_seconds,
        "collection": {
            "baseline_count": baseline_collected,
            "head_count": int(manifest["head_collected"]),
            "common_count": common_count,
            "head_only_count": head_only_count,
            "baseline_only_count": int(manifest["baseline_only_count"]),
            "common_ids_sha256": common_hash,
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
    lines.append(f"- dependency match: {report['dependency_match']}")
    lines.append(
        f"- execution order: {', '.join(report.get('execution_order', []))}"
    )
    lines.append("")

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
        f"({cs['paired_median_delta_percent']:+.1f}%)"
    )
    lines.append(
        f"- baseline median: {cs['baseline_median_seconds']:.2f}s | "
        f"HEAD median: {cs['head_median_seconds']:.2f}s"
    )
    lines.append(f"- MAD of paired deltas: {cs['mad_paired_delta']:.2f}s")
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
    lines.append(
        f"- gate (all valid, no failures): {'PASS' if ho['gate_passed'] else 'FAIL'}"
    )
    if ho["top_tests"]:
        lines.append("")
        lines.append("Top 10 HEAD-only tests by median:")
        lines.append("")
        lines.append("| median (s) | test |")
        lines.append("|---|---|")
        for t in ho["top_tests"][:10]:
            lines.append(f"| {t['median']:.3f} | `{t['test']}` |")
    lines.append("")

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
                f"{cs['paired_median_delta_percent']:+.1f}% > "
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

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--results-dir",
        type=Path,
        required=True,
        help="Directory containing collection/, selection/, pair-*/, etc.",
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
    mode_group = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument(
        "--write-selection-only",
        action="store_true",
        help="Prepare mode: compute and write selection files + manifest, then exit 0.",
    )
    mode_group.add_argument(
        "--compare",
        action="store_true",
        help="Compare mode: read timing.json results and enforce gates.",
    )
    return parser


def main() -> int:
    args = _build_parser().parse_args()

    if args.write_selection_only:
        return _run_prepare(args)

    # ---- Compare mode ----
    try:
        report = _build_comparison(
            args.results_dir,
            baseline_sha=args.baseline_sha,
            head_sha=args.head_sha,
            dependency_match=args.dependency_match == "true",
            common_regression_threshold_pct=args.common_regression_threshold_pct,
            head_full_limit_seconds=args.head_full_limit_seconds,
        )
    except ValidationError as exc:
        print(f"compare_error (input/schema): {exc}", file=sys.stderr)
        return _EXIT_INPUT_SCHEMA
    except IncompleteRunError as exc:
        print(f"compare_error (incomplete run): {exc}", file=sys.stderr)
        return _EXIT_INCOMPLETE

    # Write JSON report.
    json_path = args.results_dir / "timing-comparison.json"
    _write_json_atomic(json_path, report)

    # Write Markdown summary.
    md_path = args.results_dir / "timing-comparison.md"
    md_text = _build_markdown(report)
    _atomic_write_text(md_path, md_text)

    # Write to GITHUB_STEP_SUMMARY if available.
    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        with open(step_summary, "a", encoding="utf-8") as fh:
            fh.write(md_text)

    # Print key numbers to stdout for log visibility.
    print(
        f"timing_validation={'PASSED' if report['all_gates_passed'] else 'FAILED'}"
    )
    print(
        f"common_paired_median_delta="
        f"{report['common_suite']['paired_median_delta_seconds']:+.2f}s "
        f"({report['common_suite']['paired_median_delta_percent']:+.1f}%)"
    )
    print(
        f"head_only_median={report['head_only_suite']['median_seconds']:.2f}s"
    )
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
        return _EXIT_GATE_FAILED

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
