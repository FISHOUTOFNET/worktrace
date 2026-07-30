"""Exit-code and CLI semantics tests for the WebView comparison layer.

Covers the pure-Python functions in ``scripts/webview_comparison.py`` and
the ``_extract_webview_metrics`` function in ``scripts/webview_render_perf.py``.

These tests do NOT launch WebView2 or any subprocess — they exercise the
``SideResult`` tolerant loader, per-side revision identity checks,
cross-revision consistency, scenario isolation, metric extraction, gate
computation, fail-closed artifact writing, and exit-code semantics against
synthetic JSON payloads.

The scripts are loaded from their file paths because ``scripts/`` is not a
Python package; using ``importlib`` keeps the test hermetic and avoids
mutating ``sys.path`` globally.
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
    make_webview_result,
    write_webview_result,
)

pytestmark = [pytest.mark.unit, pytest.mark.contract, pytest.mark.parallel_safe]

ROOT = Path(__file__).resolve().parents[2]
COMPARISON_PATH = ROOT / "scripts" / "webview_comparison.py"


@pytest.fixture(scope="module")
def comparison_module():
    """Load scripts/webview_comparison.py as a module."""
    spec = importlib.util.spec_from_file_location(
        "webview_comparison_under_test", COMPARISON_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["webview_comparison_under_test"] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop("webview_comparison_under_test", None)
        raise
    return module


# ---------------------------------------------------------------------------
# Exit code semantics (webview_comparison.py main)
# ---------------------------------------------------------------------------

class TestExitCodes:
    """Verify the fail-closed exit codes and artifact writing from main()."""

    def _run_main(
        self,
        comparison_module,
        monkeypatch,
        *,
        baseline_dir: Path,
        head_dir: Path,
        output_path: Path,
        tolerance_pct: str = "10",
        extra_argv: list[str] | None = None,
    ) -> int:
        monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
        argv = [
            "webview_comparison.py",
            "--baseline-dir", str(baseline_dir),
            "--head-dir", str(head_dir),
            "--baseline-sha", BASELINE_SHA,
            "--head-sha", HEAD_SHA,
            "--tolerance-pct", tolerance_pct,
            "--output", str(output_path),
        ]
        if extra_argv:
            argv.extend(extra_argv)
        monkeypatch.setattr(sys, "argv", argv)
        return comparison_module.main()

    def test_output_is_required(
        self, comparison_module, tmp_path: Path, monkeypatch
    ) -> None:
        """Omitting --output must cause argparse to raise SystemExit."""
        monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
        monkeypatch.setattr(sys, "argv", [
            "webview_comparison.py",
            "--baseline-dir", str(tmp_path / "baseline"),
            "--head-dir", str(tmp_path / "head"),
            "--baseline-sha", BASELINE_SHA,
            "--head-sha", HEAD_SHA,
            "--tolerance-pct", "10",
        ])
        with pytest.raises(SystemExit):
            comparison_module.main()

    def test_main_returns_0_and_writes_artifact_when_gates_pass(
        self, comparison_module, tmp_path: Path, monkeypatch
    ) -> None:
        baseline_dir = tmp_path / "baseline"
        head_dir = tmp_path / "head"
        output_path = tmp_path / "out" / "comparison.json"
        write_webview_result(
            baseline_dir, make_webview_result(revision=BASELINE_SHA)
        )
        write_webview_result(
            head_dir, make_webview_result(revision=HEAD_SHA)
        )
        exit_code = self._run_main(
            comparison_module, monkeypatch,
            baseline_dir=baseline_dir, head_dir=head_dir,
            output_path=output_path,
        )
        assert exit_code == 0
        # Fail-closed: artifact is always written.
        assert output_path.is_file()
        report = json.loads(output_path.read_text(encoding="utf-8"))
        assert report["outcome"] == "comparison_passed"
        assert report["baseline_sha"] == BASELINE_SHA
        assert report["head_sha"] == HEAD_SHA

    def test_main_returns_4_on_gate_failure(
        self, comparison_module, tmp_path: Path, monkeypatch
    ) -> None:
        baseline_dir = tmp_path / "baseline"
        head_dir = tmp_path / "head"
        output_path = tmp_path / "out" / "comparison.json"
        write_webview_result(
            baseline_dir,
            make_webview_result(
                revision=BASELINE_SHA,
                metrics={
                    "cold_timeline_seconds": {
                        "samples_seconds": [1.0], "median_seconds": 1.0,
                    },
                    "warm_timeline_seconds": {
                        "samples_seconds": [0.9, 0.9, 0.9], "median_seconds": 0.9,
                    },
                    "detail_payload_seconds": {
                        "samples_seconds": [0.05, 0.05, 0.05], "median_seconds": 0.05,
                    },
                    "detail_total_seconds": {
                        "samples_seconds": [0.2, 0.2, 0.2], "median_seconds": 0.2,
                    },
                },
            ),
        )
        # 50% regression on every metric — exceeds 10%.
        write_webview_result(
            head_dir,
            make_webview_result(
                revision=HEAD_SHA,
                metrics={
                    "cold_timeline_seconds": {
                        "samples_seconds": [1.5], "median_seconds": 1.5,
                    },
                    "warm_timeline_seconds": {
                        "samples_seconds": [1.35, 1.35, 1.35], "median_seconds": 1.35,
                    },
                    "detail_payload_seconds": {
                        "samples_seconds": [0.075, 0.075, 0.075], "median_seconds": 0.075,
                    },
                    "detail_total_seconds": {
                        "samples_seconds": [0.3, 0.3, 0.3], "median_seconds": 0.3,
                    },
                },
            ),
        )
        exit_code = self._run_main(
            comparison_module, monkeypatch,
            baseline_dir=baseline_dir, head_dir=head_dir,
            output_path=output_path,
        )
        assert exit_code == 4
        # Fail-closed: artifact is always written even on gate failure.
        assert output_path.is_file()
        report = json.loads(output_path.read_text(encoding="utf-8"))
        assert report["outcome"] == "comparison_gate_failed"

    def test_main_returns_0_when_baseline_missing_and_writes_artifact(
        self, comparison_module, tmp_path: Path, monkeypatch
    ) -> None:
        """Missing baseline artifact is fail-closed: outcome=baseline_invalid,
        exit 0, and an artifact is still written."""
        baseline_dir = tmp_path / "baseline"  # no artifact written
        head_dir = tmp_path / "head"
        output_path = tmp_path / "out" / "comparison.json"
        write_webview_result(head_dir, make_webview_result(revision=HEAD_SHA))
        exit_code = self._run_main(
            comparison_module, monkeypatch,
            baseline_dir=baseline_dir, head_dir=head_dir,
            output_path=output_path,
        )
        assert exit_code == 0
        assert output_path.is_file()
        report = json.loads(output_path.read_text(encoding="utf-8"))
        assert report["outcome"] == "baseline_invalid"
        assert report["baseline"]["present"] is False
        assert report["head"]["valid"] is True

    def test_main_returns_0_when_head_missing_and_writes_artifact(
        self, comparison_module, tmp_path: Path, monkeypatch
    ) -> None:
        """Missing head artifact is fail-closed: outcome=head_invalid, exit 0."""
        baseline_dir = tmp_path / "baseline"
        head_dir = tmp_path / "head"  # no artifact written
        output_path = tmp_path / "out" / "comparison.json"
        write_webview_result(
            baseline_dir, make_webview_result(revision=BASELINE_SHA)
        )
        exit_code = self._run_main(
            comparison_module, monkeypatch,
            baseline_dir=baseline_dir, head_dir=head_dir,
            output_path=output_path,
        )
        assert exit_code == 0
        assert output_path.is_file()
        report = json.loads(output_path.read_text(encoding="utf-8"))
        assert report["outcome"] == "head_invalid"
        assert report["head"]["present"] is False
        assert report["baseline"]["valid"] is True

    def test_main_returns_0_when_both_missing_and_writes_artifact(
        self, comparison_module, tmp_path: Path, monkeypatch
    ) -> None:
        baseline_dir = tmp_path / "baseline"  # no artifact
        head_dir = tmp_path / "head"  # no artifact
        output_path = tmp_path / "out" / "comparison.json"
        exit_code = self._run_main(
            comparison_module, monkeypatch,
            baseline_dir=baseline_dir, head_dir=head_dir,
            output_path=output_path,
        )
        assert exit_code == 0
        assert output_path.is_file()
        report = json.loads(output_path.read_text(encoding="utf-8"))
        assert report["outcome"] == "both_invalid"
        assert report["baseline"]["present"] is False
        assert report["head"]["present"] is False

    def test_main_returns_2_on_sample_count_mismatch_and_writes_failure_artifact(
        self, comparison_module, tmp_path: Path, monkeypatch
    ) -> None:
        """Sample count mismatch raises ComparisonError in _build_comparison;
        main catches it, writes a failure artifact (fail-closed), returns 2."""
        baseline_dir = tmp_path / "baseline"
        head_dir = tmp_path / "head"
        output_path = tmp_path / "out" / "comparison.json"
        write_webview_result(
            baseline_dir,
            make_webview_result(
                revision=BASELINE_SHA,
                metrics={
                    "cold_timeline_seconds": {
                        "samples_seconds": [1.0, 1.0], "median_seconds": 1.0,
                    },
                    "warm_timeline_seconds": {
                        "samples_seconds": [0.9], "median_seconds": 0.9,
                    },
                    "detail_payload_seconds": {
                        "samples_seconds": [0.05], "median_seconds": 0.05,
                    },
                    "detail_total_seconds": {
                        "samples_seconds": [0.2], "median_seconds": 0.2,
                    },
                },
            ),
        )
        write_webview_result(
            head_dir,
            make_webview_result(
                revision=HEAD_SHA,
                metrics={
                    "cold_timeline_seconds": {
                        "samples_seconds": [1.0], "median_seconds": 1.0,
                    },
                    "warm_timeline_seconds": {
                        "samples_seconds": [0.9], "median_seconds": 0.9,
                    },
                    "detail_payload_seconds": {
                        "samples_seconds": [0.05], "median_seconds": 0.05,
                    },
                    "detail_total_seconds": {
                        "samples_seconds": [0.2], "median_seconds": 0.2,
                    },
                },
            ),
        )
        exit_code = self._run_main(
            comparison_module, monkeypatch,
            baseline_dir=baseline_dir, head_dir=head_dir,
            output_path=output_path,
        )
        assert exit_code == 2
        # Fail-closed: artifact is written even on input/schema error.
        assert output_path.is_file()
        report = json.loads(output_path.read_text(encoding="utf-8"))
        assert report["outcome"] == "both_invalid"
        assert "comparison_error" in report
        assert "sample count" in report["comparison_error"]

    def test_main_writes_artifact_on_consistency_error(
        self, comparison_module, tmp_path: Path, monkeypatch
    ) -> None:
        """When both sides are valid but consistency fails, _build_comparison
        returns a report (does not raise); main writes it and returns 0
        (not a gate failure or schema error)."""
        baseline_dir = tmp_path / "baseline"
        head_dir = tmp_path / "head"
        output_path = tmp_path / "out" / "comparison.json"
        write_webview_result(
            baseline_dir,
            make_webview_result(revision=BASELINE_SHA, driver_version="1.0"),
        )
        write_webview_result(
            head_dir,
            make_webview_result(revision=HEAD_SHA, driver_version="2.0"),
        )
        exit_code = self._run_main(
            comparison_module, monkeypatch,
            baseline_dir=baseline_dir, head_dir=head_dir,
            output_path=output_path,
        )
        # Consistency error → outcome both_invalid → exit 0 (not gate failure).
        assert exit_code == 0
        assert output_path.is_file()
        report = json.loads(output_path.read_text(encoding="utf-8"))
        assert report["outcome"] == "both_invalid"
        assert "consistency_error" in report
        assert "driver_version" in report["consistency_error"]

    def test_main_does_not_accept_scenario_argument(
        self, comparison_module, tmp_path: Path, monkeypatch
    ) -> None:
        """WebView comparison does NOT take --scenario (unlike product
        benchmark comparison).  Passing it must be rejected by argparse."""
        baseline_dir = tmp_path / "baseline"
        head_dir = tmp_path / "head"
        output_path = tmp_path / "out" / "comparison.json"
        write_webview_result(
            baseline_dir, make_webview_result(revision=BASELINE_SHA)
        )
        write_webview_result(
            head_dir, make_webview_result(revision=HEAD_SHA)
        )
        monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
        monkeypatch.setattr(sys, "argv", [
            "webview_comparison.py",
            "--baseline-dir", str(baseline_dir),
            "--head-dir", str(head_dir),
            "--baseline-sha", BASELINE_SHA,
            "--head-sha", HEAD_SHA,
            "--tolerance-pct", "10",
            "--output", str(output_path),
            "--scenario", "webview_render",  # should be rejected
        ])
        with pytest.raises(SystemExit):
            comparison_module.main()
