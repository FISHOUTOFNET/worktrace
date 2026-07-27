"""SideResult loader tests for the product benchmark comparison layer.

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
import sys
from pathlib import Path
from typing import Any

import pytest

from tests.support.performance_artifact_factory import (
    BASELINE_SHA,
    make_product_failure,
    make_product_fixture_audit,
    make_product_progress,
    make_product_result,
    make_product_side,
    write_json,
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
# SideResult
# ---------------------------------------------------------------------------

class TestSideResult:
    """Tests for the SideResult loader.

    SideResult reads result.json (success path) OR progress.json +
    failure.json (failure path) from a driver output directory.
    """

    def test_valid_result_loads_and_is_valid(
        self, comparison_module, tmp_path: Path
    ) -> None:
        payload = make_product_result(revision=BASELINE_SHA)
        side = make_product_side(
            comparison_module, tmp_path / "baseline",
            result=payload, expected_sha=BASELINE_SHA,
        )
        assert side.valid is True
        assert side.result is not None
        assert side.result["requested_revision"] == BASELINE_SHA
        assert side.result_present is True

    def test_result_missing_progress_present_is_invalid(
        self, comparison_module, tmp_path: Path
    ) -> None:
        progress = make_product_progress(revision=BASELINE_SHA, phase="warmup")
        side = make_product_side(
            comparison_module, tmp_path / "baseline",
            progress=progress, expected_sha=BASELINE_SHA,
        )
        assert side.valid is False
        assert side.result is None
        assert side.progress is not None
        assert side.progress_present is True
        assert side.last_phase == "warmup"

    def test_neither_result_nor_progress_raises(
        self, comparison_module, tmp_path: Path
    ) -> None:
        with pytest.raises(comparison_module.ComparisonError, match="neither"):
            comparison_module.SideResult(
                label="baseline",
                output_dir=tmp_path / "empty",
                expected_sha=BASELINE_SHA,
                scenario="20k_activities",
            )

    def test_failure_only_without_progress_raises(
        self, comparison_module, tmp_path: Path
    ) -> None:
        # failure.json alone is not enough — need result.json or progress.json.
        d = tmp_path / "baseline"
        write_json(d / "failure.json", make_product_failure())
        with pytest.raises(comparison_module.ComparisonError, match="neither"):
            comparison_module.SideResult(
                label="baseline",
                output_dir=d,
                expected_sha=BASELINE_SHA,
                scenario="20k_activities",
            )

    def test_invalid_result_json_raises(
        self, comparison_module, tmp_path: Path
    ) -> None:
        d = tmp_path / "baseline"
        d.mkdir(parents=True)
        (d / "result.json").write_text("{not valid", encoding="utf-8")
        with pytest.raises(comparison_module.ComparisonError, match="cannot parse"):
            comparison_module.SideResult(
                label="baseline",
                output_dir=d,
                expected_sha=BASELINE_SHA,
                scenario="20k_activities",
            )

    def test_invalid_progress_json_raises(
        self, comparison_module, tmp_path: Path
    ) -> None:
        d = tmp_path / "baseline"
        d.mkdir(parents=True)
        (d / "progress.json").write_text("not json", encoding="utf-8")
        with pytest.raises(comparison_module.ComparisonError, match="cannot parse"):
            comparison_module.SideResult(
                label="baseline",
                output_dir=d,
                expected_sha=BASELINE_SHA,
                scenario="20k_activities",
            )

    def test_invalid_failure_json_raises(
        self, comparison_module, tmp_path: Path
    ) -> None:
        d = tmp_path / "baseline"
        write_json(d / "progress.json", make_product_progress(revision=BASELINE_SHA))
        (d / "failure.json").write_text("not json", encoding="utf-8")
        with pytest.raises(comparison_module.ComparisonError, match="cannot parse"):
            comparison_module.SideResult(
                label="baseline",
                output_dir=d,
                expected_sha=BASELINE_SHA,
                scenario="20k_activities",
            )

    def test_invalid_reason_from_failure(
        self, comparison_module, tmp_path: Path
    ) -> None:
        progress = make_product_progress(revision=BASELINE_SHA)
        failure = make_product_failure(
            failure_category="db_error", failure_message="connection refused"
        )
        side = make_product_side(
            comparison_module, tmp_path / "baseline",
            progress=progress, failure=failure, expected_sha=BASELINE_SHA,
        )
        assert side.valid is False
        assert side.failure_category == "db_error"
        assert side.failure_message == "connection refused"
        assert "db_error" in side.invalid_reason
        assert "connection refused" in side.invalid_reason

    def test_invalid_reason_from_progress_when_no_failure(
        self, comparison_module, tmp_path: Path
    ) -> None:
        progress = make_product_progress(revision=BASELINE_SHA, phase="fixture")
        side = make_product_side(
            comparison_module, tmp_path / "baseline",
            progress=progress, expected_sha=BASELINE_SHA,
        )
        assert side.valid is False
        assert "fixture" in side.invalid_reason

    def test_invalid_reason_empty_for_valid_side(
        self, comparison_module, tmp_path: Path
    ) -> None:
        payload = make_product_result(revision=BASELINE_SHA)
        side = make_product_side(
            comparison_module, tmp_path / "baseline",
            result=payload, expected_sha=BASELINE_SHA,
        )
        assert side.valid is True
        assert side.invalid_reason == ""

    def test_completed_samples_from_progress(
        self, comparison_module, tmp_path: Path
    ) -> None:
        progress = make_product_progress(
            revision=BASELINE_SHA, completed_samples=3
        )
        side = make_product_side(
            comparison_module, tmp_path / "baseline",
            progress=progress, expected_sha=BASELINE_SHA,
        )
        assert side.completed_samples == 3

    def test_completed_samples_from_result(
        self, comparison_module, tmp_path: Path
    ) -> None:
        payload = make_product_result(
            revision=BASELINE_SHA,
            metrics={
                "projection_20k_total_seconds": {
                    "samples_seconds": [1.0, 2.0, 3.0, 4.0],
                    "median_seconds": 2.5,
                    "consistency_hash": "h",
                },
            },
        )
        side = make_product_side(
            comparison_module, tmp_path / "baseline",
            result=payload, expected_sha=BASELINE_SHA,
        )
        assert side.completed_samples == 4

    def test_fixture_audit_from_result(
        self, comparison_module, tmp_path: Path
    ) -> None:
        audit = make_product_fixture_audit(scenario="20k_activities", requested_count=20000)
        payload = make_product_result(
            revision=BASELINE_SHA, fixture_audit=audit
        )
        side = make_product_side(
            comparison_module, tmp_path / "baseline",
            result=payload, expected_sha=BASELINE_SHA,
        )
        assert side.fixture_audit == audit

    def test_fixture_audit_from_progress(
        self, comparison_module, tmp_path: Path
    ) -> None:
        audit = make_product_fixture_audit(scenario="20k_activities")
        progress = make_product_progress(
            revision=BASELINE_SHA, fixture_audit=audit
        )
        side = make_product_side(
            comparison_module, tmp_path / "baseline",
            progress=progress, expected_sha=BASELINE_SHA,
        )
        assert side.fixture_audit == audit

    def test_revision_fields_from_result(
        self, comparison_module, tmp_path: Path
    ) -> None:
        payload = make_product_result(revision=BASELINE_SHA)
        side = make_product_side(
            comparison_module, tmp_path / "baseline",
            result=payload, expected_sha=BASELINE_SHA,
        )
        assert side.requested_revision == BASELINE_SHA
        assert side.actual_target_revision == BASELINE_SHA
        assert side.driver_version == "1.0"
        assert side.fixture_hash == "fixedhash"
        assert side.python_version == "3.11.5"

    def test_revision_fields_fall_back_to_progress(
        self, comparison_module, tmp_path: Path
    ) -> None:
        progress = make_product_progress(revision=BASELINE_SHA)
        side = make_product_side(
            comparison_module, tmp_path / "baseline",
            progress=progress, expected_sha=BASELINE_SHA,
        )
        assert side.requested_revision == BASELINE_SHA
        assert side.actual_target_revision == BASELINE_SHA
        assert side.driver_version == "1.0"
        assert side.fixture_hash == "fixedhash"
        # python_version is only read from result, not progress.
        assert side.python_version == ""

    def test_last_step_result_completed(
        self, comparison_module, tmp_path: Path
    ) -> None:
        payload = make_product_result(revision=BASELINE_SHA)
        side = make_product_side(
            comparison_module, tmp_path / "baseline",
            result=payload, expected_sha=BASELINE_SHA,
        )
        assert side.last_phase == "result_completed"

    def test_runner_metadata_from_result(
        self, comparison_module, tmp_path: Path
    ) -> None:
        payload = make_product_result(
            revision=BASELINE_SHA,
            runner_metadata={"runner_name": "ubuntu-latest"},
        )
        side = make_product_side(
            comparison_module, tmp_path / "baseline",
            result=payload, expected_sha=BASELINE_SHA,
        )
        assert side.runner_metadata == {"runner_name": "ubuntu-latest"}
