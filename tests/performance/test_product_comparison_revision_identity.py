"""Revision identity validation tests for the product benchmark comparison.

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
    make_product_progress,
    make_product_result,
    make_product_side,
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
# _validate_revision_identity
# ---------------------------------------------------------------------------

class TestValidateRevisionIdentity:
    """Tests for per-side revision identity validation.

    ``_validate_revision_identity`` checks that requested == actual ==
    expected for one side, even when only progress.json is present.
    """

    def test_valid_identity_passes(
        self, comparison_module, tmp_path: Path
    ) -> None:
        payload = make_product_result(revision=BASELINE_SHA)
        side = make_product_side(
            comparison_module, tmp_path / "baseline",
            result=payload, expected_sha=BASELINE_SHA,
        )
        comparison_module._validate_revision_identity(side)

    def test_missing_requested_raises(
        self, comparison_module, tmp_path: Path
    ) -> None:
        payload = make_product_result(revision=BASELINE_SHA)
        del payload["requested_revision"]
        side = make_product_side(
            comparison_module, tmp_path / "baseline",
            result=payload, expected_sha=BASELINE_SHA,
        )
        with pytest.raises(comparison_module.ComparisonError, match="missing"):
            comparison_module._validate_revision_identity(side)

    def test_missing_actual_raises(
        self, comparison_module, tmp_path: Path
    ) -> None:
        payload = make_product_result(revision=BASELINE_SHA)
        del payload["actual_target_revision"]
        side = make_product_side(
            comparison_module, tmp_path / "baseline",
            result=payload, expected_sha=BASELINE_SHA,
        )
        with pytest.raises(comparison_module.ComparisonError, match="missing"):
            comparison_module._validate_revision_identity(side)

    def test_requested_not_equal_actual_raises(
        self, comparison_module, tmp_path: Path
    ) -> None:
        payload = make_product_result(
            revision=BASELINE_SHA,
            actual_target_revision=BASELINE_SHA + "deadbeef",
        )
        side = make_product_side(
            comparison_module, tmp_path / "baseline",
            result=payload, expected_sha=BASELINE_SHA,
        )
        with pytest.raises(
            comparison_module.ComparisonError, match="requested_revision"
        ):
            comparison_module._validate_revision_identity(side)

    def test_actual_not_equal_expected_raises(
        self, comparison_module, tmp_path: Path
    ) -> None:
        payload = make_product_result(revision=BASELINE_SHA)
        # expected_sha doesn't match actual_target_revision
        side = make_product_side(
            comparison_module, tmp_path / "baseline",
            result=payload, expected_sha="c" * 40,
        )
        with pytest.raises(comparison_module.ComparisonError, match="expected"):
            comparison_module._validate_revision_identity(side)

    def test_identity_validated_from_progress(
        self, comparison_module, tmp_path: Path
    ) -> None:
        """Even without result.json, revision identity is checked from
        progress.json — so a requested/actual mismatch is still
        detectable."""
        progress = make_product_progress(
            revision=BASELINE_SHA,
            actual_target_revision="wrongsha",
        )
        side = make_product_side(
            comparison_module, tmp_path / "baseline",
            progress=progress, expected_sha=BASELINE_SHA,
        )
        with pytest.raises(
            comparison_module.ComparisonError, match="requested_revision"
        ):
            comparison_module._validate_revision_identity(side)

    def test_github_workflow_sha_not_used_for_identity(
        self, comparison_module, tmp_path: Path
    ) -> None:
        """github_workflow_sha may differ from actual_target_revision
        (it can be a merge commit SHA in pull_request workflows) and must
        NOT cause an identity mismatch."""
        payload = make_product_result(
            revision=BASELINE_SHA,
            github_workflow_sha="mergecommitsha1234",
        )
        side = make_product_side(
            comparison_module, tmp_path / "baseline",
            result=payload, expected_sha=BASELINE_SHA,
        )
        comparison_module._validate_revision_identity(side)
