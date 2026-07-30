"""Exit-code and CLI semantics tests for the product benchmark comparison.

Covers the pure-Python functions in ``scripts/benchmark_comparison.py``:
the scenario-scoped ``SideResult`` loader, per-side revision identity
validation, cross-revision consistency checks, per-scenario fixture
isolation, metric extraction, gate computation, and fail-closed
exit-code semantics.

The comparison is scenario-scoped: each invocation compares exactly one
scenario (``--scenario``) and reads ``result.json`` from the baseline and
HEAD driver output directories.  When ``result.json`` is missing on
either side, the comparison reads ``progress.json`` and ``failure.json``
so the artifact can still report the last completed phase, the failure
category, and any partial samples.

The script is loaded from its file path because ``scripts/`` is not a
Python package; using ``importlib`` keeps the test hermetic.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

from tests.support.performance_artifact_factory import (
    BASELINE_SHA,
    HEAD_SHA,
    make_product_progress,
    make_product_result,
    write_json,
    write_product_result,
)

pytestmark = [pytest.mark.unit, pytest.mark.contract, pytest.mark.parallel_safe]

ROOT = Path(__file__).resolve().parents[2]
COMPARISON_PATH = ROOT / "scripts" / "benchmark_comparison.py"


@pytest.fixture(scope="module")
def comparison_module():
    """Load scripts/benchmark_comparison.py as a module."""
    spec = importlib.util.spec_from_file_location(
        "benchmark_comparison_under_test", COMPARISON_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["benchmark_comparison_under_test"] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop("benchmark_comparison_under_test", None)
        raise
    return module


# ---------------------------------------------------------------------------
# Exit code semantics (main)
# ---------------------------------------------------------------------------

class TestExitCodes:
    """Verify the fail-closed exit codes and artifact writing from main().

    Exit codes:
      0  comparison passed, or one/both sides invalid (artifact written)
      2  input/schema error (artifact still written when possible)
      4  gate failure (both sides valid, HEAD regressed beyond tolerance)
    """

    @staticmethod
    def _invoke(
        comparison_module,
        monkeypatch,
        argv: list[str],
    ) -> int:
        monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
        monkeypatch.setattr(sys, "argv", argv)
        return comparison_module.main()

    def test_main_returns_0_on_comparison_passed(
        self, comparison_module, tmp_path: Path, monkeypatch
    ) -> None:
        baseline_dir = tmp_path / "baseline"
        head_dir = tmp_path / "head"
        output = tmp_path / "out" / "comparison.json"
        write_product_result(
            baseline_dir, make_product_result(revision=BASELINE_SHA)
        )
        write_product_result(
            head_dir, make_product_result(revision=HEAD_SHA)
        )
        exit_code = self._invoke(comparison_module, monkeypatch, [
            "benchmark_comparison.py",
            "--scenario", "20k_activities",
            "--baseline-dir", str(baseline_dir),
            "--head-dir", str(head_dir),
            "--baseline-sha", BASELINE_SHA,
            "--head-sha", HEAD_SHA,
            "--tolerance-pct", "10",
            "--output", str(output),
        ])
        assert exit_code == 0
        assert output.is_file()
        artifact = json.loads(output.read_text(encoding="utf-8"))
        assert artifact["outcome"] == "comparison_passed"

    def test_main_returns_4_on_gate_failure(
        self, comparison_module, tmp_path: Path, monkeypatch
    ) -> None:
        baseline_dir = tmp_path / "baseline"
        head_dir = tmp_path / "head"
        output = tmp_path / "out" / "comparison.json"
        write_product_result(
            baseline_dir,
            make_product_result(
                revision=BASELINE_SHA,
                metrics={"projection_20k_total_seconds": {
                    "samples_seconds": [1.0, 1.0, 1.0],
                    "median_seconds": 1.0,
                    "consistency_hash": "hash20k",
                }},
            ),
        )
        # 50% regression — exceeds 10%.
        write_product_result(
            head_dir,
            make_product_result(
                revision=HEAD_SHA,
                metrics={"projection_20k_total_seconds": {
                    "samples_seconds": [1.5, 1.5, 1.5],
                    "median_seconds": 1.5,
                    "consistency_hash": "hash20k",
                }},
            ),
        )
        exit_code = self._invoke(comparison_module, monkeypatch, [
            "benchmark_comparison.py",
            "--scenario", "20k_activities",
            "--baseline-dir", str(baseline_dir),
            "--head-dir", str(head_dir),
            "--baseline-sha", BASELINE_SHA,
            "--head-sha", HEAD_SHA,
            "--tolerance-pct", "10",
            "--output", str(output),
        ])
        assert exit_code == 4
        assert output.is_file()
        artifact = json.loads(output.read_text(encoding="utf-8"))
        assert artifact["outcome"] == "comparison_gate_failed"

    def test_main_returns_0_on_baseline_invalid(
        self, comparison_module, tmp_path: Path, monkeypatch
    ) -> None:
        """One side invalid → exit 0 (the artifact records the failure
        mode in its outcome field)."""
        baseline_dir = tmp_path / "baseline"
        head_dir = tmp_path / "head"
        output = tmp_path / "out" / "comparison.json"
        write_json(
            baseline_dir / "progress.json",
            make_product_progress(revision=BASELINE_SHA),
        )
        write_product_result(
            head_dir, make_product_result(revision=HEAD_SHA)
        )
        exit_code = self._invoke(comparison_module, monkeypatch, [
            "benchmark_comparison.py",
            "--scenario", "20k_activities",
            "--baseline-dir", str(baseline_dir),
            "--head-dir", str(head_dir),
            "--baseline-sha", BASELINE_SHA,
            "--head-sha", HEAD_SHA,
            "--tolerance-pct", "10",
            "--output", str(output),
        ])
        assert exit_code == 0
        artifact = json.loads(output.read_text(encoding="utf-8"))
        assert artifact["outcome"] == "baseline_invalid"

    def test_main_returns_0_on_head_invalid(
        self, comparison_module, tmp_path: Path, monkeypatch
    ) -> None:
        baseline_dir = tmp_path / "baseline"
        head_dir = tmp_path / "head"
        output = tmp_path / "out" / "comparison.json"
        write_product_result(
            baseline_dir, make_product_result(revision=BASELINE_SHA)
        )
        write_json(
            head_dir / "progress.json",
            make_product_progress(revision=HEAD_SHA),
        )
        exit_code = self._invoke(comparison_module, monkeypatch, [
            "benchmark_comparison.py",
            "--scenario", "20k_activities",
            "--baseline-dir", str(baseline_dir),
            "--head-dir", str(head_dir),
            "--baseline-sha", BASELINE_SHA,
            "--head-sha", HEAD_SHA,
            "--tolerance-pct", "10",
            "--output", str(output),
        ])
        assert exit_code == 0
        artifact = json.loads(output.read_text(encoding="utf-8"))
        assert artifact["outcome"] == "head_invalid"

    def test_main_returns_0_on_both_invalid(
        self, comparison_module, tmp_path: Path, monkeypatch
    ) -> None:
        baseline_dir = tmp_path / "baseline"
        head_dir = tmp_path / "head"
        output = tmp_path / "out" / "comparison.json"
        write_json(
            baseline_dir / "progress.json",
            make_product_progress(revision=BASELINE_SHA),
        )
        write_json(
            head_dir / "progress.json",
            make_product_progress(revision=HEAD_SHA),
        )
        exit_code = self._invoke(comparison_module, monkeypatch, [
            "benchmark_comparison.py",
            "--scenario", "20k_activities",
            "--baseline-dir", str(baseline_dir),
            "--head-dir", str(head_dir),
            "--baseline-sha", BASELINE_SHA,
            "--head-sha", HEAD_SHA,
            "--tolerance-pct", "10",
            "--output", str(output),
        ])
        assert exit_code == 0
        artifact = json.loads(output.read_text(encoding="utf-8"))
        assert artifact["outcome"] == "both_invalid"

    def test_main_returns_0_on_baseline_invalid_when_no_artifacts(
        self, comparison_module, tmp_path: Path, monkeypatch
    ) -> None:
        """When baseline has no result.json and no progress.json (driver
        crashed before writing artifacts), main() writes a fail-closed
        artifact with outcome=baseline_invalid and exits 0."""
        baseline_dir = tmp_path / "baseline"
        head_dir = tmp_path / "head"
        output = tmp_path / "out" / "comparison.json"
        baseline_dir.mkdir(parents=True)  # empty — no result.json, no progress.json
        write_product_result(
            head_dir, make_product_result(revision=HEAD_SHA)
        )
        exit_code = self._invoke(comparison_module, monkeypatch, [
            "benchmark_comparison.py",
            "--scenario", "20k_activities",
            "--baseline-dir", str(baseline_dir),
            "--head-dir", str(head_dir),
            "--baseline-sha", BASELINE_SHA,
            "--head-sha", HEAD_SHA,
            "--tolerance-pct", "10",
            "--output", str(output),
        ])
        assert exit_code == 0
        assert output.is_file()
        artifact = json.loads(output.read_text(encoding="utf-8"))
        assert artifact["outcome"] == "baseline_invalid"
        assert artifact["baseline"]["valid"] is False
        assert artifact["head"]["valid"] is True

    def test_artifact_always_written_even_when_both_sides_empty(
        self, comparison_module, tmp_path: Path, monkeypatch
    ) -> None:
        """The comparison always writes an artifact, even when both sides
        have no artifacts — the workflow's if: always() upload step relies
        on this."""
        baseline_dir = tmp_path / "baseline"
        head_dir = tmp_path / "head"
        output = tmp_path / "out" / "comparison.json"
        baseline_dir.mkdir(parents=True)
        head_dir.mkdir(parents=True)
        exit_code = self._invoke(comparison_module, monkeypatch, [
            "benchmark_comparison.py",
            "--scenario", "20k_activities",
            "--baseline-dir", str(baseline_dir),
            "--head-dir", str(head_dir),
            "--baseline-sha", BASELINE_SHA,
            "--head-sha", HEAD_SHA,
            "--tolerance-pct", "10",
            "--output", str(output),
        ])
        assert exit_code == 0
        assert output.is_file()
        artifact = json.loads(output.read_text(encoding="utf-8"))
        assert artifact["outcome"] == "both_invalid"
        assert artifact["baseline"]["valid"] is False
        assert artifact["head"]["valid"] is False

    def test_scenario_required(
        self, comparison_module, tmp_path: Path, monkeypatch
    ) -> None:
        """Omitting --scenario causes argparse to exit with code 2."""
        baseline_dir = tmp_path / "baseline"
        head_dir = tmp_path / "head"
        output = tmp_path / "out" / "comparison.json"
        write_product_result(
            baseline_dir, make_product_result(revision=BASELINE_SHA)
        )
        write_product_result(
            head_dir, make_product_result(revision=HEAD_SHA)
        )
        monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
        monkeypatch.setattr(sys, "argv", [
            "benchmark_comparison.py",
            "--baseline-dir", str(baseline_dir),
            "--head-dir", str(head_dir),
            "--baseline-sha", BASELINE_SHA,
            "--head-sha", HEAD_SHA,
            "--tolerance-pct", "10",
            "--output", str(output),
        ])
        with pytest.raises(SystemExit) as exc_info:
            comparison_module.main()
        assert exc_info.value.code == 2

    def test_output_required(
        self, comparison_module, tmp_path: Path, monkeypatch
    ) -> None:
        """Omitting --output causes argparse to exit with code 2."""
        baseline_dir = tmp_path / "baseline"
        head_dir = tmp_path / "head"
        write_product_result(
            baseline_dir, make_product_result(revision=BASELINE_SHA)
        )
        write_product_result(
            head_dir, make_product_result(revision=HEAD_SHA)
        )
        monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
        monkeypatch.setattr(sys, "argv", [
            "benchmark_comparison.py",
            "--scenario", "20k_activities",
            "--baseline-dir", str(baseline_dir),
            "--head-dir", str(head_dir),
            "--baseline-sha", BASELINE_SHA,
            "--head-sha", HEAD_SHA,
            "--tolerance-pct", "10",
        ])
        with pytest.raises(SystemExit) as exc_info:
            comparison_module.main()
        assert exc_info.value.code == 2
