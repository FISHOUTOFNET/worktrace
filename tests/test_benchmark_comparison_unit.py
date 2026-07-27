"""Unit tests for the product benchmark comparison layer.

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

pytestmark = [pytest.mark.unit, pytest.mark.contract, pytest.mark.parallel_safe]

ROOT = Path(__file__).resolve().parents[1]
COMPARISON_PATH = ROOT / "scripts" / "benchmark_comparison.py"

_BASELINE_SHA = "a" * 40
_HEAD_SHA = "b" * 40


# ---------------------------------------------------------------------------
# Module loading fixture
# ---------------------------------------------------------------------------

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
# Helpers
# ---------------------------------------------------------------------------

def _make_fixture_audit(
    *,
    scenario: str = "20k_activities",
    requested_count: int = 20000,
    inserted_count: int | None = None,
    preexisting_activity_count: int = 0,
    connection_count: int = 1,
    commit_count: int = 41,
) -> dict[str, Any]:
    """Build a synthetic but contract-valid single-scenario fixture_audit.

    The new schema records ``fixture_audit`` as a single object (not a
    dict keyed by scenario name) because the comparison is
    scenario-scoped — each driver invocation produces one scenario's
    result.json with one fixture_audit.
    """
    return {
        "scenario": scenario,
        "requested_count": requested_count,
        "inserted_count": inserted_count if inserted_count is not None else requested_count,
        "preexisting_activity_count": preexisting_activity_count,
        "fixture_build_seconds": 1.0,
        "connection_count": connection_count,
        "commit_count": commit_count,
        "chunk_size": 500,
        "builder_version": "1.0",
        "report_date": "2026-07-15",
    }


def _make_driver_payload(
    *,
    revision: str,
    scenario: str = "20k_activities",
    metrics: dict[str, Any] | None = None,
    driver_version: str = "1.0",
    fixture_hash: str = "fixedhash",
    python_version: str = "3.11.5",
    target_root: str = "/tmp/worktree",
    fixture_audit: dict[str, Any] | None = None,
    actual_target_revision: str | None = None,
    github_workflow_sha: str | None = None,
    runner_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a synthetic but schema-valid product benchmark driver result.

    Schema v3 records both ``requested_revision`` (from ``--revision``) and
    ``actual_target_revision`` (from ``git rev-parse HEAD`` on the target
    worktree).  The two must match within an artifact and must match the
    expected SHA supplied on the CLI.  ``github_workflow_sha`` is recorded
    for diagnostics only and is never used for identity comparison.

    Only the metric relevant to ``scenario`` is included by default (the
    memory metric lives in the compact_memory_driver now).
    """
    if scenario == "10k_contributions":
        default_metric_key = "projection_10k_contributions_seconds"
        default_requested_count = 10000
    else:
        default_metric_key = "projection_20k_total_seconds"
        default_requested_count = 20000
    if metrics is None:
        metrics = {
            default_metric_key: {
                "samples_seconds": [1.0, 1.05, 0.98],
                "median_seconds": 1.0,
                "consistency_hash": "hash_" + default_metric_key,
            },
        }
    if fixture_audit is None:
        fixture_audit = _make_fixture_audit(
            scenario=scenario, requested_count=default_requested_count
        )
    return {
        "schema_version": 3,
        "requested_revision": revision,
        "actual_target_revision": actual_target_revision or revision,
        "github_workflow_sha": github_workflow_sha,
        "driver_version": driver_version,
        "fixture_hash": fixture_hash,
        "python_version": python_version,
        "target_root": target_root,
        "fixture_audit": fixture_audit,
        "metrics": metrics,
        "runner_metadata": runner_metadata or {},
    }


def _make_progress_payload(
    *,
    revision: str,
    scenario: str = "20k_activities",
    phase: str = "projection",
    completed_samples: int = 2,
    driver_version: str = "1.0",
    fixture_hash: str = "fixedhash",
    fixture_audit: dict[str, Any] | None = None,
    actual_target_revision: str | None = None,
) -> dict[str, Any]:
    """Build a synthetic progress.json payload.

    When result.json is missing, the comparison reads progress.json to
    recover the last completed phase, completed sample count, revision
    identity, and fixture audit.
    """
    if fixture_audit is None:
        fixture_audit = _make_fixture_audit(scenario=scenario)
    return {
        "schema_version": 3,
        "phase": phase,
        "completed_samples": completed_samples,
        "requested_revision": revision,
        "actual_target_revision": actual_target_revision or revision,
        "driver_version": driver_version,
        "fixture_hash": fixture_hash,
        "fixture_audit": fixture_audit,
    }


def _make_failure_payload(
    *,
    failure_category: str = "driver_error",
    failure_message: str = "boom",
) -> dict[str, Any]:
    """Build a synthetic failure.json payload."""
    return {
        "failure_category": failure_category,
        "failure_message": failure_message,
    }


def _write_json(path: Path, payload: dict[str, Any]) -> Path:
    """Write a JSON payload to an arbitrary path, creating parents."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def _write_driver_result(
    output_dir: Path,
    payload: dict[str, Any],
) -> Path:
    """Write a driver ``result.json`` into ``output_dir``.

    The new driver writes to ``result.json`` (not ``product-benchmark.json``)
    in its output directory.
    """
    return _write_json(output_dir / "result.json", payload)


def _make_side(
    module: Any,
    output_dir: Path,
    *,
    label: str = "baseline",
    expected_sha: str = _BASELINE_SHA,
    scenario: str = "20k_activities",
    result: dict[str, Any] | None = None,
    progress: dict[str, Any] | None = None,
    failure: dict[str, Any] | None = None,
) -> Any:
    """Write artifacts into ``output_dir`` and return a ``SideResult``.

    At least one of ``result`` or ``progress`` must be provided —
    ``SideResult`` raises ``ComparisonError`` if neither is present.
    """
    if result is not None:
        _write_json(output_dir / "result.json", result)
    if progress is not None:
        _write_json(output_dir / "progress.json", progress)
    if failure is not None:
        _write_json(output_dir / "failure.json", failure)
    return module.SideResult(
        label=label,
        output_dir=output_dir,
        expected_sha=expected_sha,
        scenario=scenario,
    )


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
        payload = _make_driver_payload(revision=_BASELINE_SHA)
        side = _make_side(
            comparison_module, tmp_path / "baseline",
            result=payload, expected_sha=_BASELINE_SHA,
        )
        assert side.valid is True
        assert side.result is not None
        assert side.result["requested_revision"] == _BASELINE_SHA
        assert side.result_present is True

    def test_result_missing_progress_present_is_invalid(
        self, comparison_module, tmp_path: Path
    ) -> None:
        progress = _make_progress_payload(revision=_BASELINE_SHA, phase="warmup")
        side = _make_side(
            comparison_module, tmp_path / "baseline",
            progress=progress, expected_sha=_BASELINE_SHA,
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
                expected_sha=_BASELINE_SHA,
                scenario="20k_activities",
            )

    def test_failure_only_without_progress_raises(
        self, comparison_module, tmp_path: Path
    ) -> None:
        # failure.json alone is not enough — need result.json or progress.json.
        d = tmp_path / "baseline"
        _write_json(d / "failure.json", _make_failure_payload())
        with pytest.raises(comparison_module.ComparisonError, match="neither"):
            comparison_module.SideResult(
                label="baseline",
                output_dir=d,
                expected_sha=_BASELINE_SHA,
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
                expected_sha=_BASELINE_SHA,
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
                expected_sha=_BASELINE_SHA,
                scenario="20k_activities",
            )

    def test_invalid_failure_json_raises(
        self, comparison_module, tmp_path: Path
    ) -> None:
        d = tmp_path / "baseline"
        _write_json(d / "progress.json", _make_progress_payload(revision=_BASELINE_SHA))
        (d / "failure.json").write_text("not json", encoding="utf-8")
        with pytest.raises(comparison_module.ComparisonError, match="cannot parse"):
            comparison_module.SideResult(
                label="baseline",
                output_dir=d,
                expected_sha=_BASELINE_SHA,
                scenario="20k_activities",
            )

    def test_invalid_reason_from_failure(
        self, comparison_module, tmp_path: Path
    ) -> None:
        progress = _make_progress_payload(revision=_BASELINE_SHA)
        failure = _make_failure_payload(
            failure_category="db_error", failure_message="connection refused"
        )
        side = _make_side(
            comparison_module, tmp_path / "baseline",
            progress=progress, failure=failure, expected_sha=_BASELINE_SHA,
        )
        assert side.valid is False
        assert side.failure_category == "db_error"
        assert side.failure_message == "connection refused"
        assert "db_error" in side.invalid_reason
        assert "connection refused" in side.invalid_reason

    def test_invalid_reason_from_progress_when_no_failure(
        self, comparison_module, tmp_path: Path
    ) -> None:
        progress = _make_progress_payload(revision=_BASELINE_SHA, phase="fixture")
        side = _make_side(
            comparison_module, tmp_path / "baseline",
            progress=progress, expected_sha=_BASELINE_SHA,
        )
        assert side.valid is False
        assert "fixture" in side.invalid_reason

    def test_invalid_reason_empty_for_valid_side(
        self, comparison_module, tmp_path: Path
    ) -> None:
        payload = _make_driver_payload(revision=_BASELINE_SHA)
        side = _make_side(
            comparison_module, tmp_path / "baseline",
            result=payload, expected_sha=_BASELINE_SHA,
        )
        assert side.valid is True
        assert side.invalid_reason == ""

    def test_completed_samples_from_progress(
        self, comparison_module, tmp_path: Path
    ) -> None:
        progress = _make_progress_payload(
            revision=_BASELINE_SHA, completed_samples=3
        )
        side = _make_side(
            comparison_module, tmp_path / "baseline",
            progress=progress, expected_sha=_BASELINE_SHA,
        )
        assert side.completed_samples == 3

    def test_completed_samples_from_result(
        self, comparison_module, tmp_path: Path
    ) -> None:
        payload = _make_driver_payload(
            revision=_BASELINE_SHA,
            metrics={
                "projection_20k_total_seconds": {
                    "samples_seconds": [1.0, 2.0, 3.0, 4.0],
                    "median_seconds": 2.5,
                    "consistency_hash": "h",
                },
            },
        )
        side = _make_side(
            comparison_module, tmp_path / "baseline",
            result=payload, expected_sha=_BASELINE_SHA,
        )
        assert side.completed_samples == 4

    def test_fixture_audit_from_result(
        self, comparison_module, tmp_path: Path
    ) -> None:
        audit = _make_fixture_audit(scenario="20k_activities", requested_count=20000)
        payload = _make_driver_payload(
            revision=_BASELINE_SHA, fixture_audit=audit
        )
        side = _make_side(
            comparison_module, tmp_path / "baseline",
            result=payload, expected_sha=_BASELINE_SHA,
        )
        assert side.fixture_audit == audit

    def test_fixture_audit_from_progress(
        self, comparison_module, tmp_path: Path
    ) -> None:
        audit = _make_fixture_audit(scenario="20k_activities")
        progress = _make_progress_payload(
            revision=_BASELINE_SHA, fixture_audit=audit
        )
        side = _make_side(
            comparison_module, tmp_path / "baseline",
            progress=progress, expected_sha=_BASELINE_SHA,
        )
        assert side.fixture_audit == audit

    def test_revision_fields_from_result(
        self, comparison_module, tmp_path: Path
    ) -> None:
        payload = _make_driver_payload(revision=_BASELINE_SHA)
        side = _make_side(
            comparison_module, tmp_path / "baseline",
            result=payload, expected_sha=_BASELINE_SHA,
        )
        assert side.requested_revision == _BASELINE_SHA
        assert side.actual_target_revision == _BASELINE_SHA
        assert side.driver_version == "1.0"
        assert side.fixture_hash == "fixedhash"
        assert side.python_version == "3.11.5"

    def test_revision_fields_fall_back_to_progress(
        self, comparison_module, tmp_path: Path
    ) -> None:
        progress = _make_progress_payload(revision=_BASELINE_SHA)
        side = _make_side(
            comparison_module, tmp_path / "baseline",
            progress=progress, expected_sha=_BASELINE_SHA,
        )
        assert side.requested_revision == _BASELINE_SHA
        assert side.actual_target_revision == _BASELINE_SHA
        assert side.driver_version == "1.0"
        assert side.fixture_hash == "fixedhash"
        # python_version is only read from result, not progress.
        assert side.python_version == ""

    def test_last_phase_result_completed(
        self, comparison_module, tmp_path: Path
    ) -> None:
        payload = _make_driver_payload(revision=_BASELINE_SHA)
        side = _make_side(
            comparison_module, tmp_path / "baseline",
            result=payload, expected_sha=_BASELINE_SHA,
        )
        assert side.last_phase == "result_completed"

    def test_runner_metadata_from_result(
        self, comparison_module, tmp_path: Path
    ) -> None:
        payload = _make_driver_payload(
            revision=_BASELINE_SHA,
            runner_metadata={"runner_name": "ubuntu-latest"},
        )
        side = _make_side(
            comparison_module, tmp_path / "baseline",
            result=payload, expected_sha=_BASELINE_SHA,
        )
        assert side.runner_metadata == {"runner_name": "ubuntu-latest"}


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
        payload = _make_driver_payload(revision=_BASELINE_SHA)
        side = _make_side(
            comparison_module, tmp_path / "baseline",
            result=payload, expected_sha=_BASELINE_SHA,
        )
        comparison_module._validate_revision_identity(side)

    def test_missing_requested_raises(
        self, comparison_module, tmp_path: Path
    ) -> None:
        payload = _make_driver_payload(revision=_BASELINE_SHA)
        del payload["requested_revision"]
        side = _make_side(
            comparison_module, tmp_path / "baseline",
            result=payload, expected_sha=_BASELINE_SHA,
        )
        with pytest.raises(comparison_module.ComparisonError, match="missing"):
            comparison_module._validate_revision_identity(side)

    def test_missing_actual_raises(
        self, comparison_module, tmp_path: Path
    ) -> None:
        payload = _make_driver_payload(revision=_BASELINE_SHA)
        del payload["actual_target_revision"]
        side = _make_side(
            comparison_module, tmp_path / "baseline",
            result=payload, expected_sha=_BASELINE_SHA,
        )
        with pytest.raises(comparison_module.ComparisonError, match="missing"):
            comparison_module._validate_revision_identity(side)

    def test_requested_not_equal_actual_raises(
        self, comparison_module, tmp_path: Path
    ) -> None:
        payload = _make_driver_payload(
            revision=_BASELINE_SHA,
            actual_target_revision=_BASELINE_SHA + "deadbeef",
        )
        side = _make_side(
            comparison_module, tmp_path / "baseline",
            result=payload, expected_sha=_BASELINE_SHA,
        )
        with pytest.raises(
            comparison_module.ComparisonError, match="requested_revision"
        ):
            comparison_module._validate_revision_identity(side)

    def test_actual_not_equal_expected_raises(
        self, comparison_module, tmp_path: Path
    ) -> None:
        payload = _make_driver_payload(revision=_BASELINE_SHA)
        # expected_sha doesn't match actual_target_revision
        side = _make_side(
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
        progress = _make_progress_payload(
            revision=_BASELINE_SHA,
            actual_target_revision="wrongsha",
        )
        side = _make_side(
            comparison_module, tmp_path / "baseline",
            progress=progress, expected_sha=_BASELINE_SHA,
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
        payload = _make_driver_payload(
            revision=_BASELINE_SHA,
            github_workflow_sha="mergecommitsha1234",
        )
        side = _make_side(
            comparison_module, tmp_path / "baseline",
            result=payload, expected_sha=_BASELINE_SHA,
        )
        comparison_module._validate_revision_identity(side)


# ---------------------------------------------------------------------------
# _validate_cross_revision_consistency
# ---------------------------------------------------------------------------

class TestValidateCrossRevisionConsistency:
    """Tests for the cross-revision consistency checks.

    ``_validate_cross_revision_consistency`` cross-checks driver_version,
    fixture_hash, and Python major.minor between baseline and HEAD.
    """

    def test_consistent_sides_pass(
        self, comparison_module, tmp_path: Path
    ) -> None:
        baseline = _make_side(
            comparison_module, tmp_path / "baseline",
            result=_make_driver_payload(revision=_BASELINE_SHA),
            expected_sha=_BASELINE_SHA,
        )
        head = _make_side(
            comparison_module, tmp_path / "head",
            result=_make_driver_payload(revision=_HEAD_SHA),
            expected_sha=_HEAD_SHA,
        )
        comparison_module._validate_cross_revision_consistency(baseline, head)

    def test_driver_version_mismatch_raises(
        self, comparison_module, tmp_path: Path
    ) -> None:
        baseline = _make_side(
            comparison_module, tmp_path / "baseline",
            result=_make_driver_payload(
                revision=_BASELINE_SHA, driver_version="1.0"
            ),
            expected_sha=_BASELINE_SHA,
        )
        head = _make_side(
            comparison_module, tmp_path / "head",
            result=_make_driver_payload(
                revision=_HEAD_SHA, driver_version="2.0"
            ),
            expected_sha=_HEAD_SHA,
        )
        with pytest.raises(
            comparison_module.ComparisonError, match="driver_version"
        ):
            comparison_module._validate_cross_revision_consistency(baseline, head)

    def test_fixture_hash_mismatch_raises(
        self, comparison_module, tmp_path: Path
    ) -> None:
        baseline = _make_side(
            comparison_module, tmp_path / "baseline",
            result=_make_driver_payload(
                revision=_BASELINE_SHA, fixture_hash="hashA"
            ),
            expected_sha=_BASELINE_SHA,
        )
        head = _make_side(
            comparison_module, tmp_path / "head",
            result=_make_driver_payload(
                revision=_HEAD_SHA, fixture_hash="hashB"
            ),
            expected_sha=_HEAD_SHA,
        )
        with pytest.raises(
            comparison_module.ComparisonError, match="fixture_hash"
        ):
            comparison_module._validate_cross_revision_consistency(baseline, head)

    def test_fixture_hash_empty_on_one_side_skipped(
        self, comparison_module, tmp_path: Path
    ) -> None:
        """If one side has an empty fixture_hash, the check is skipped."""
        baseline = _make_side(
            comparison_module, tmp_path / "baseline",
            result=_make_driver_payload(
                revision=_BASELINE_SHA, fixture_hash=""
            ),
            expected_sha=_BASELINE_SHA,
        )
        head = _make_side(
            comparison_module, tmp_path / "head",
            result=_make_driver_payload(
                revision=_HEAD_SHA, fixture_hash="hashB"
            ),
            expected_sha=_HEAD_SHA,
        )
        comparison_module._validate_cross_revision_consistency(baseline, head)

    def test_python_major_minor_mismatch_raises(
        self, comparison_module, tmp_path: Path
    ) -> None:
        baseline = _make_side(
            comparison_module, tmp_path / "baseline",
            result=_make_driver_payload(
                revision=_BASELINE_SHA, python_version="3.11.5"
            ),
            expected_sha=_BASELINE_SHA,
        )
        head = _make_side(
            comparison_module, tmp_path / "head",
            result=_make_driver_payload(
                revision=_HEAD_SHA, python_version="3.12.1"
            ),
            expected_sha=_HEAD_SHA,
        )
        with pytest.raises(
            comparison_module.ComparisonError, match="python_version"
        ):
            comparison_module._validate_cross_revision_consistency(baseline, head)

    def test_python_patch_difference_allowed(
        self, comparison_module, tmp_path: Path
    ) -> None:
        baseline = _make_side(
            comparison_module, tmp_path / "baseline",
            result=_make_driver_payload(
                revision=_BASELINE_SHA, python_version="3.11.5"
            ),
            expected_sha=_BASELINE_SHA,
        )
        head = _make_side(
            comparison_module, tmp_path / "head",
            result=_make_driver_payload(
                revision=_HEAD_SHA, python_version="3.11.9"
            ),
            expected_sha=_HEAD_SHA,
        )
        comparison_module._validate_cross_revision_consistency(baseline, head)


# ---------------------------------------------------------------------------
# _validate_scenario_isolation
# ---------------------------------------------------------------------------

class TestValidateScenarioIsolation:
    """Tests for the per-side fixture_audit isolation contract.

    ``_validate_scenario_isolation`` takes a ``SideResult`` and verifies
    its ``fixture_audit`` reports clean isolation:
      * ``preexisting_activity_count == 0`` (no carryover),
      * ``inserted_count == requested_count`` (every row inserted),
      * ``connection_count >= 1`` (the O(1) connection contract held),
      * ``commit_count >= 1`` (at least one commit happened).
    """

    def test_clean_audit_passes(
        self, comparison_module, tmp_path: Path
    ) -> None:
        side = _make_side(
            comparison_module, tmp_path / "baseline",
            result=_make_driver_payload(revision=_BASELINE_SHA),
            expected_sha=_BASELINE_SHA,
        )
        comparison_module._validate_scenario_isolation(side)

    def test_empty_fixture_audit_raises(
        self, comparison_module, tmp_path: Path
    ) -> None:
        payload = _make_driver_payload(
            revision=_BASELINE_SHA, fixture_audit={},
        )
        side = _make_side(
            comparison_module, tmp_path / "baseline",
            result=payload, expected_sha=_BASELINE_SHA,
        )
        with pytest.raises(comparison_module.ComparisonError, match="empty"):
            comparison_module._validate_scenario_isolation(side)

    def test_fixture_audit_not_object_raises(
        self, comparison_module, tmp_path: Path
    ) -> None:
        payload = _make_driver_payload(revision=_BASELINE_SHA)
        payload["fixture_audit"] = "not-an-object"
        side = _make_side(
            comparison_module, tmp_path / "baseline",
            result=payload, expected_sha=_BASELINE_SHA,
        )
        with pytest.raises(
            comparison_module.ComparisonError, match="fixture_audit"
        ):
            comparison_module._validate_scenario_isolation(side)

    def test_preexisting_activity_count_nonzero_raises(
        self, comparison_module, tmp_path: Path
    ) -> None:
        audit = _make_fixture_audit(preexisting_activity_count=5)
        payload = _make_driver_payload(
            revision=_BASELINE_SHA, fixture_audit=audit,
        )
        side = _make_side(
            comparison_module, tmp_path / "baseline",
            result=payload, expected_sha=_BASELINE_SHA,
        )
        with pytest.raises(
            comparison_module.ComparisonError, match="preexisting_activity_count"
        ):
            comparison_module._validate_scenario_isolation(side)

    def test_inserted_count_mismatch_raises(
        self, comparison_module, tmp_path: Path
    ) -> None:
        audit = _make_fixture_audit(inserted_count=19999)
        payload = _make_driver_payload(
            revision=_BASELINE_SHA, fixture_audit=audit,
        )
        side = _make_side(
            comparison_module, tmp_path / "baseline",
            result=payload, expected_sha=_BASELINE_SHA,
        )
        with pytest.raises(
            comparison_module.ComparisonError, match="inserted_count"
        ):
            comparison_module._validate_scenario_isolation(side)

    def test_connection_count_zero_raises(
        self, comparison_module, tmp_path: Path
    ) -> None:
        audit = _make_fixture_audit(connection_count=0)
        payload = _make_driver_payload(
            revision=_BASELINE_SHA, fixture_audit=audit,
        )
        side = _make_side(
            comparison_module, tmp_path / "baseline",
            result=payload, expected_sha=_BASELINE_SHA,
        )
        with pytest.raises(
            comparison_module.ComparisonError, match="connection_count"
        ):
            comparison_module._validate_scenario_isolation(side)

    def test_commit_count_zero_raises(
        self, comparison_module, tmp_path: Path
    ) -> None:
        audit = _make_fixture_audit(commit_count=0)
        payload = _make_driver_payload(
            revision=_BASELINE_SHA, fixture_audit=audit,
        )
        side = _make_side(
            comparison_module, tmp_path / "baseline",
            result=payload, expected_sha=_BASELINE_SHA,
        )
        with pytest.raises(
            comparison_module.ComparisonError, match="commit_count"
        ):
            comparison_module._validate_scenario_isolation(side)

    def test_isolation_checked_from_progress(
        self, comparison_module, tmp_path: Path
    ) -> None:
        """When only progress.json is present, fixture_audit is read from
        progress — isolation is still validated."""
        audit = _make_fixture_audit(preexisting_activity_count=3)
        progress = _make_progress_payload(
            revision=_BASELINE_SHA, fixture_audit=audit,
        )
        side = _make_side(
            comparison_module, tmp_path / "baseline",
            progress=progress, expected_sha=_BASELINE_SHA,
        )
        with pytest.raises(
            comparison_module.ComparisonError, match="preexisting_activity_count"
        ):
            comparison_module._validate_scenario_isolation(side)


# ---------------------------------------------------------------------------
# _extract_metric
# ---------------------------------------------------------------------------

class TestExtractMetric:
    """Tests for extracting a single gated metric from a SideResult.

    ``_extract_metric`` takes a ``SideResult`` (not a dict) plus
    keyword-only ``metric_key``, ``value_field``, ``sample_field``.
    """

    def test_valid_metric_returns_median_and_samples(
        self, comparison_module, tmp_path: Path
    ) -> None:
        side = _make_side(
            comparison_module, tmp_path / "baseline",
            result=_make_driver_payload(revision=_BASELINE_SHA),
            expected_sha=_BASELINE_SHA,
        )
        median, samples = comparison_module._extract_metric(
            side,
            metric_key="projection_20k_total_seconds",
            value_field="median_seconds",
            sample_field="samples_seconds",
        )
        assert median == 1.0
        assert samples == [1.0, 1.05, 0.98]

    def test_missing_metric_raises(
        self, comparison_module, tmp_path: Path
    ) -> None:
        side = _make_side(
            comparison_module, tmp_path / "baseline",
            result=_make_driver_payload(revision=_BASELINE_SHA, metrics={}),
            expected_sha=_BASELINE_SHA,
        )
        with pytest.raises(comparison_module.ComparisonError, match="missing"):
            comparison_module._extract_metric(
                side,
                metric_key="projection_20k_total_seconds",
                value_field="median_seconds",
                sample_field="samples_seconds",
            )

    def test_metric_not_object_raises(
        self, comparison_module, tmp_path: Path
    ) -> None:
        payload = _make_driver_payload(
            revision=_BASELINE_SHA,
            metrics={"projection_20k_total_seconds": "not-an-object"},
        )
        side = _make_side(
            comparison_module, tmp_path / "baseline",
            result=payload, expected_sha=_BASELINE_SHA,
        )
        with pytest.raises(comparison_module.ComparisonError, match="not object"):
            comparison_module._extract_metric(
                side,
                metric_key="projection_20k_total_seconds",
                value_field="median_seconds",
                sample_field="samples_seconds",
            )

    def test_missing_value_field_raises(
        self, comparison_module, tmp_path: Path
    ) -> None:
        payload = _make_driver_payload(
            revision=_BASELINE_SHA,
            metrics={"projection_20k_total_seconds": {"samples_seconds": [1.0]}},
        )
        side = _make_side(
            comparison_module, tmp_path / "baseline",
            result=payload, expected_sha=_BASELINE_SHA,
        )
        with pytest.raises(
            comparison_module.ComparisonError, match="median_seconds"
        ):
            comparison_module._extract_metric(
                side,
                metric_key="projection_20k_total_seconds",
                value_field="median_seconds",
                sample_field="samples_seconds",
            )

    def test_missing_sample_field_raises(
        self, comparison_module, tmp_path: Path
    ) -> None:
        payload = _make_driver_payload(
            revision=_BASELINE_SHA,
            metrics={"projection_20k_total_seconds": {"median_seconds": 1.0}},
        )
        side = _make_side(
            comparison_module, tmp_path / "baseline",
            result=payload, expected_sha=_BASELINE_SHA,
        )
        with pytest.raises(
            comparison_module.ComparisonError, match="samples_seconds"
        ):
            comparison_module._extract_metric(
                side,
                metric_key="projection_20k_total_seconds",
                value_field="median_seconds",
                sample_field="samples_seconds",
            )

    def test_samples_not_list_raises(
        self, comparison_module, tmp_path: Path
    ) -> None:
        payload = _make_driver_payload(
            revision=_BASELINE_SHA,
            metrics={"projection_20k_total_seconds": {
                "median_seconds": 1.0,
                "samples_seconds": "not-a-list",
            }},
        )
        side = _make_side(
            comparison_module, tmp_path / "baseline",
            result=payload, expected_sha=_BASELINE_SHA,
        )
        with pytest.raises(comparison_module.ComparisonError, match="not a list"):
            comparison_module._extract_metric(
                side,
                metric_key="projection_20k_total_seconds",
                value_field="median_seconds",
                sample_field="samples_seconds",
            )

    def test_zero_samples_raises_comparison_error(
        self, comparison_module, tmp_path: Path
    ) -> None:
        """Zero samples raises ComparisonError (not IncompleteError —
        that class no longer exists in the new API)."""
        payload = _make_driver_payload(
            revision=_BASELINE_SHA,
            metrics={"projection_20k_total_seconds": {
                "median_seconds": 0.0,
                "samples_seconds": [],
            }},
        )
        side = _make_side(
            comparison_module, tmp_path / "baseline",
            result=payload, expected_sha=_BASELINE_SHA,
        )
        with pytest.raises(comparison_module.ComparisonError, match="zero samples"):
            comparison_module._extract_metric(
                side,
                metric_key="projection_20k_total_seconds",
                value_field="median_seconds",
                sample_field="samples_seconds",
            )

    def test_10k_contributions_metric(
        self, comparison_module, tmp_path: Path
    ) -> None:
        side = _make_side(
            comparison_module, tmp_path / "baseline",
            result=_make_driver_payload(
                revision=_BASELINE_SHA, scenario="10k_contributions"
            ),
            expected_sha=_BASELINE_SHA,
            scenario="10k_contributions",
        )
        median, samples = comparison_module._extract_metric(
            side,
            metric_key="projection_10k_contributions_seconds",
            value_field="median_seconds",
            sample_field="samples_seconds",
        )
        assert median == 1.0
        assert samples == [1.0, 1.05, 0.98]


# ---------------------------------------------------------------------------
# _percent_delta
# ---------------------------------------------------------------------------

class TestPercentDelta:
    """Tests for the percentage delta computation."""

    def test_zero_baseline_zero_head_returns_zero(
        self, comparison_module
    ) -> None:
        assert comparison_module._percent_delta(0.0, 0.0) == 0.0

    def test_zero_baseline_nonzero_head_returns_100(
        self, comparison_module
    ) -> None:
        assert comparison_module._percent_delta(0.0, 1.0) == 100.0

    def test_improvement_returns_negative(self, comparison_module) -> None:
        assert comparison_module._percent_delta(1.0, 0.8) == pytest.approx(-20.0)

    def test_regression_returns_positive(self, comparison_module) -> None:
        assert comparison_module._percent_delta(1.0, 1.15) == pytest.approx(15.0)

    def test_boundary_10pct_regression(self, comparison_module) -> None:
        # head=1.10, baseline=1.0 -> exactly +10% (gate passes with <= 10)
        assert comparison_module._percent_delta(1.0, 1.10) == pytest.approx(10.0)


# ---------------------------------------------------------------------------
# _build_comparison
# ---------------------------------------------------------------------------

class TestBuildComparison:
    """Tests for the full comparison builder including outcome semantics.

    ``_build_comparison`` is scenario-scoped (requires ``--scenario``)
    and always returns an artifact dict with an ``outcome`` field.
    """

    def _make_dirs(
        self,
        tmp_path: Path,
        *,
        baseline_payload: dict[str, Any] | None = None,
        head_payload: dict[str, Any] | None = None,
        baseline_progress: dict[str, Any] | None = None,
        head_progress: dict[str, Any] | None = None,
    ) -> tuple[Path, Path]:
        baseline_dir = tmp_path / "baseline"
        head_dir = tmp_path / "head"
        if baseline_payload is not None:
            _write_driver_result(baseline_dir, baseline_payload)
        if head_payload is not None:
            _write_driver_result(head_dir, head_payload)
        if baseline_progress is not None:
            _write_json(baseline_dir / "progress.json", baseline_progress)
        if head_progress is not None:
            _write_json(head_dir / "progress.json", head_progress)
        return baseline_dir, head_dir

    def test_comparison_passed_when_head_not_regressed(
        self, comparison_module, tmp_path: Path
    ) -> None:
        baseline_dir, head_dir = self._make_dirs(
            tmp_path,
            baseline_payload=_make_driver_payload(
                revision=_BASELINE_SHA,
                metrics={"projection_20k_total_seconds": {
                    "samples_seconds": [1.0, 1.0, 1.0],
                    "median_seconds": 1.0,
                    "consistency_hash": "hash20k",
                }},
            ),
            head_payload=_make_driver_payload(
                revision=_HEAD_SHA,
                metrics={"projection_20k_total_seconds": {
                    "samples_seconds": [0.95, 0.95, 0.95],
                    "median_seconds": 0.95,
                    "consistency_hash": "hash20k",
                }},
            ),
        )
        report = comparison_module._build_comparison(
            scenario="20k_activities",
            baseline_dir=baseline_dir,
            head_dir=head_dir,
            baseline_sha=_BASELINE_SHA,
            head_sha=_HEAD_SHA,
            tolerance_pct=10.0,
        )
        assert report["outcome"] == "comparison_passed"
        assert report["gated_metric"] is not None
        assert report["gated_metric"]["gate_passed"] is True
        assert report["consistency_match"] is True

    def test_comparison_gate_failed_when_head_regressed(
        self, comparison_module, tmp_path: Path
    ) -> None:
        # 15% regression (1.0 -> 1.15) — exceeds 10% tolerance.
        baseline_dir, head_dir = self._make_dirs(
            tmp_path,
            baseline_payload=_make_driver_payload(
                revision=_BASELINE_SHA,
                metrics={"projection_20k_total_seconds": {
                    "samples_seconds": [1.0, 1.0, 1.0],
                    "median_seconds": 1.0,
                    "consistency_hash": "hash20k",
                }},
            ),
            head_payload=_make_driver_payload(
                revision=_HEAD_SHA,
                metrics={"projection_20k_total_seconds": {
                    "samples_seconds": [1.15, 1.15, 1.15],
                    "median_seconds": 1.15,
                    "consistency_hash": "hash20k",
                }},
            ),
        )
        report = comparison_module._build_comparison(
            scenario="20k_activities",
            baseline_dir=baseline_dir,
            head_dir=head_dir,
            baseline_sha=_BASELINE_SHA,
            head_sha=_HEAD_SHA,
            tolerance_pct=10.0,
        )
        assert report["outcome"] == "comparison_gate_failed"
        assert report["gated_metric"]["gate_passed"] is False
        assert report["gated_metric"]["delta_pct"] == pytest.approx(15.0)

    def test_baseline_invalid_when_baseline_result_missing(
        self, comparison_module, tmp_path: Path
    ) -> None:
        """Missing result.json on baseline (progress present) →
        baseline_invalid.  The artifact is still produced."""
        baseline_dir, head_dir = self._make_dirs(
            tmp_path,
            baseline_progress=_make_progress_payload(revision=_BASELINE_SHA),
            head_payload=_make_driver_payload(revision=_HEAD_SHA),
        )
        report = comparison_module._build_comparison(
            scenario="20k_activities",
            baseline_dir=baseline_dir,
            head_dir=head_dir,
            baseline_sha=_BASELINE_SHA,
            head_sha=_HEAD_SHA,
            tolerance_pct=10.0,
        )
        assert report["outcome"] == "baseline_invalid"
        assert report["gated_metric"] is None
        assert report["baseline"]["valid"] is False
        assert report["head"]["valid"] is True

    def test_head_invalid_when_head_result_missing(
        self, comparison_module, tmp_path: Path
    ) -> None:
        baseline_dir, head_dir = self._make_dirs(
            tmp_path,
            baseline_payload=_make_driver_payload(revision=_BASELINE_SHA),
            head_progress=_make_progress_payload(revision=_HEAD_SHA),
        )
        report = comparison_module._build_comparison(
            scenario="20k_activities",
            baseline_dir=baseline_dir,
            head_dir=head_dir,
            baseline_sha=_BASELINE_SHA,
            head_sha=_HEAD_SHA,
            tolerance_pct=10.0,
        )
        assert report["outcome"] == "head_invalid"
        assert report["gated_metric"] is None
        assert report["baseline"]["valid"] is True
        assert report["head"]["valid"] is False

    def test_both_invalid_when_neither_result_present(
        self, comparison_module, tmp_path: Path
    ) -> None:
        baseline_dir, head_dir = self._make_dirs(
            tmp_path,
            baseline_progress=_make_progress_payload(revision=_BASELINE_SHA),
            head_progress=_make_progress_payload(revision=_HEAD_SHA),
        )
        report = comparison_module._build_comparison(
            scenario="20k_activities",
            baseline_dir=baseline_dir,
            head_dir=head_dir,
            baseline_sha=_BASELINE_SHA,
            head_sha=_HEAD_SHA,
            tolerance_pct=10.0,
        )
        assert report["outcome"] == "both_invalid"
        assert report["gated_metric"] is None
        assert report["baseline"]["valid"] is False
        assert report["head"]["valid"] is False

    def test_both_invalid_on_consistency_error(
        self, comparison_module, tmp_path: Path
    ) -> None:
        """When both sides are valid but consistency checks fail, the
        outcome is both_invalid with a consistency_error message."""
        baseline_dir, head_dir = self._make_dirs(
            tmp_path,
            baseline_payload=_make_driver_payload(
                revision=_BASELINE_SHA, driver_version="1.0"
            ),
            head_payload=_make_driver_payload(
                revision=_HEAD_SHA, driver_version="2.0"
            ),
        )
        report = comparison_module._build_comparison(
            scenario="20k_activities",
            baseline_dir=baseline_dir,
            head_dir=head_dir,
            baseline_sha=_BASELINE_SHA,
            head_sha=_HEAD_SHA,
            tolerance_pct=10.0,
        )
        assert report["outcome"] == "both_invalid"
        assert report["gated_metric"] is None
        assert "consistency_error" in report
        assert "driver_version" in report["consistency_error"]

    def test_both_invalid_on_isolation_error(
        self, comparison_module, tmp_path: Path
    ) -> None:
        """Scenario isolation failure on one side also produces
        both_invalid with a consistency_error message."""
        bad_audit = _make_fixture_audit(preexisting_activity_count=5)
        baseline_dir, head_dir = self._make_dirs(
            tmp_path,
            baseline_payload=_make_driver_payload(
                revision=_BASELINE_SHA, fixture_audit=bad_audit
            ),
            head_payload=_make_driver_payload(revision=_HEAD_SHA),
        )
        report = comparison_module._build_comparison(
            scenario="20k_activities",
            baseline_dir=baseline_dir,
            head_dir=head_dir,
            baseline_sha=_BASELINE_SHA,
            head_sha=_HEAD_SHA,
            tolerance_pct=10.0,
        )
        assert report["outcome"] == "both_invalid"
        assert "consistency_error" in report
        assert "preexisting_activity_count" in report["consistency_error"]

    def test_unknown_scenario_raises(
        self, comparison_module, tmp_path: Path
    ) -> None:
        baseline_dir, head_dir = self._make_dirs(
            tmp_path,
            baseline_payload=_make_driver_payload(revision=_BASELINE_SHA),
            head_payload=_make_driver_payload(revision=_HEAD_SHA),
        )
        with pytest.raises(
            comparison_module.ComparisonError, match="unknown scenario"
        ):
            comparison_module._build_comparison(
                scenario="bogus",
                baseline_dir=baseline_dir,
                head_dir=head_dir,
                baseline_sha=_BASELINE_SHA,
                head_sha=_HEAD_SHA,
                tolerance_pct=10.0,
            )

    def test_sample_count_mismatch_raises(
        self, comparison_module, tmp_path: Path
    ) -> None:
        baseline_dir, head_dir = self._make_dirs(
            tmp_path,
            baseline_payload=_make_driver_payload(
                revision=_BASELINE_SHA,
                metrics={"projection_20k_total_seconds": {
                    "samples_seconds": [1.0, 1.0],
                    "median_seconds": 1.0,
                    "consistency_hash": "hash20k",
                }},
            ),
            head_payload=_make_driver_payload(
                revision=_HEAD_SHA,
                metrics={"projection_20k_total_seconds": {
                    "samples_seconds": [1.0],
                    "median_seconds": 1.0,
                    "consistency_hash": "hash20k",
                }},
            ),
        )
        with pytest.raises(comparison_module.ComparisonError, match="sample count"):
            comparison_module._build_comparison(
                scenario="20k_activities",
                baseline_dir=baseline_dir,
                head_dir=head_dir,
                baseline_sha=_BASELINE_SHA,
                head_sha=_HEAD_SHA,
                tolerance_pct=10.0,
            )

    def test_artifact_structure(
        self, comparison_module, tmp_path: Path
    ) -> None:
        baseline_dir, head_dir = self._make_dirs(
            tmp_path,
            baseline_payload=_make_driver_payload(revision=_BASELINE_SHA),
            head_payload=_make_driver_payload(revision=_HEAD_SHA),
        )
        report = comparison_module._build_comparison(
            scenario="20k_activities",
            baseline_dir=baseline_dir,
            head_dir=head_dir,
            baseline_sha=_BASELINE_SHA,
            head_sha=_HEAD_SHA,
            tolerance_pct=10.0,
        )
        assert report["schema_version"] == 3
        assert report["scenario"] == "20k_activities"
        assert report["metric_key"] == "projection_20k_total_seconds"
        assert report["baseline_sha"] == _BASELINE_SHA
        assert report["head_sha"] == _HEAD_SHA
        assert report["tolerance_pct"] == 10.0
        assert "baseline" in report
        assert "head" in report
        assert "gated_metric" in report
        assert "consistency_match" in report
        row = report["gated_metric"]
        assert row["metric"] == "projection_20k_total_seconds"
        assert row["unit"] == "seconds"
        for field in (
            "baseline_samples", "head_samples",
            "baseline_median", "head_median",
            "baseline_min", "baseline_max",
            "head_min", "head_max",
            "delta", "delta_pct",
            "baseline_consistency_hash", "head_consistency_hash",
            "gate_passed", "tolerance_pct",
        ):
            assert field in row

    def test_10k_contributions_scenario(
        self, comparison_module, tmp_path: Path
    ) -> None:
        baseline_dir, head_dir = self._make_dirs(
            tmp_path,
            baseline_payload=_make_driver_payload(
                revision=_BASELINE_SHA, scenario="10k_contributions",
                metrics={"projection_10k_contributions_seconds": {
                    "samples_seconds": [0.5, 0.5, 0.5],
                    "median_seconds": 0.5,
                    "consistency_hash": "hash10k",
                }},
            ),
            head_payload=_make_driver_payload(
                revision=_HEAD_SHA, scenario="10k_contributions",
                metrics={"projection_10k_contributions_seconds": {
                    "samples_seconds": [0.48, 0.48, 0.48],
                    "median_seconds": 0.48,
                    "consistency_hash": "hash10k",
                }},
            ),
        )
        report = comparison_module._build_comparison(
            scenario="10k_contributions",
            baseline_dir=baseline_dir,
            head_dir=head_dir,
            baseline_sha=_BASELINE_SHA,
            head_sha=_HEAD_SHA,
            tolerance_pct=10.0,
        )
        assert report["outcome"] == "comparison_passed"
        assert report["metric_key"] == "projection_10k_contributions_seconds"
        assert report["gated_metric"]["metric"] == (
            "projection_10k_contributions_seconds"
        )

    def test_consistency_hash_mismatch_recorded(
        self, comparison_module, tmp_path: Path
    ) -> None:
        """When the per-metric consistency_hash differs between baseline
        and head, consistency_match is False but the gate can still
        pass (the hash is diagnostic, not gating)."""
        baseline_dir, head_dir = self._make_dirs(
            tmp_path,
            baseline_payload=_make_driver_payload(
                revision=_BASELINE_SHA,
                metrics={"projection_20k_total_seconds": {
                    "samples_seconds": [1.0, 1.0, 1.0],
                    "median_seconds": 1.0,
                    "consistency_hash": "hashA",
                }},
            ),
            head_payload=_make_driver_payload(
                revision=_HEAD_SHA,
                metrics={"projection_20k_total_seconds": {
                    "samples_seconds": [0.95, 0.95, 0.95],
                    "median_seconds": 0.95,
                    "consistency_hash": "hashB",
                }},
            ),
        )
        report = comparison_module._build_comparison(
            scenario="20k_activities",
            baseline_dir=baseline_dir,
            head_dir=head_dir,
            baseline_sha=_BASELINE_SHA,
            head_sha=_HEAD_SHA,
            tolerance_pct=10.0,
        )
        assert report["consistency_match"] is False
        assert report["outcome"] == "comparison_passed"

    def test_side_diagnostics_in_artifact(
        self, comparison_module, tmp_path: Path
    ) -> None:
        """The artifact includes per-side diagnostics with result_present,
        valid, last_phase, fixture_audit, and revision fields."""
        baseline_dir, head_dir = self._make_dirs(
            tmp_path,
            baseline_payload=_make_driver_payload(revision=_BASELINE_SHA),
            head_payload=_make_driver_payload(revision=_HEAD_SHA),
        )
        report = comparison_module._build_comparison(
            scenario="20k_activities",
            baseline_dir=baseline_dir,
            head_dir=head_dir,
            baseline_sha=_BASELINE_SHA,
            head_sha=_HEAD_SHA,
            tolerance_pct=10.0,
        )
        for side_label in ("baseline", "head"):
            side = report[side_label]
            assert side["label"] == side_label
            assert side["result_present"] is True
            assert side["valid"] is True
            assert side["last_phase"] == "result_completed"
            assert side["requested_revision"] != ""
            assert side["actual_target_revision"] != ""
            assert side["expected_revision"] != ""
            assert "fixture_audit" in side
            assert "output_dir" in side


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
        _write_driver_result(
            baseline_dir, _make_driver_payload(revision=_BASELINE_SHA)
        )
        _write_driver_result(
            head_dir, _make_driver_payload(revision=_HEAD_SHA)
        )
        exit_code = self._invoke(comparison_module, monkeypatch, [
            "benchmark_comparison.py",
            "--scenario", "20k_activities",
            "--baseline-dir", str(baseline_dir),
            "--head-dir", str(head_dir),
            "--baseline-sha", _BASELINE_SHA,
            "--head-sha", _HEAD_SHA,
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
        _write_driver_result(
            baseline_dir,
            _make_driver_payload(
                revision=_BASELINE_SHA,
                metrics={"projection_20k_total_seconds": {
                    "samples_seconds": [1.0, 1.0, 1.0],
                    "median_seconds": 1.0,
                    "consistency_hash": "hash20k",
                }},
            ),
        )
        # 50% regression — exceeds 10%.
        _write_driver_result(
            head_dir,
            _make_driver_payload(
                revision=_HEAD_SHA,
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
            "--baseline-sha", _BASELINE_SHA,
            "--head-sha", _HEAD_SHA,
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
        _write_json(
            baseline_dir / "progress.json",
            _make_progress_payload(revision=_BASELINE_SHA),
        )
        _write_driver_result(
            head_dir, _make_driver_payload(revision=_HEAD_SHA)
        )
        exit_code = self._invoke(comparison_module, monkeypatch, [
            "benchmark_comparison.py",
            "--scenario", "20k_activities",
            "--baseline-dir", str(baseline_dir),
            "--head-dir", str(head_dir),
            "--baseline-sha", _BASELINE_SHA,
            "--head-sha", _HEAD_SHA,
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
        _write_driver_result(
            baseline_dir, _make_driver_payload(revision=_BASELINE_SHA)
        )
        _write_json(
            head_dir / "progress.json",
            _make_progress_payload(revision=_HEAD_SHA),
        )
        exit_code = self._invoke(comparison_module, monkeypatch, [
            "benchmark_comparison.py",
            "--scenario", "20k_activities",
            "--baseline-dir", str(baseline_dir),
            "--head-dir", str(head_dir),
            "--baseline-sha", _BASELINE_SHA,
            "--head-sha", _HEAD_SHA,
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
        _write_json(
            baseline_dir / "progress.json",
            _make_progress_payload(revision=_BASELINE_SHA),
        )
        _write_json(
            head_dir / "progress.json",
            _make_progress_payload(revision=_HEAD_SHA),
        )
        exit_code = self._invoke(comparison_module, monkeypatch, [
            "benchmark_comparison.py",
            "--scenario", "20k_activities",
            "--baseline-dir", str(baseline_dir),
            "--head-dir", str(head_dir),
            "--baseline-sha", _BASELINE_SHA,
            "--head-sha", _HEAD_SHA,
            "--tolerance-pct", "10",
            "--output", str(output),
        ])
        assert exit_code == 0
        artifact = json.loads(output.read_text(encoding="utf-8"))
        assert artifact["outcome"] == "both_invalid"

    def test_main_returns_2_and_writes_artifact_on_input_error(
        self, comparison_module, tmp_path: Path, monkeypatch
    ) -> None:
        """When _build_comparison raises (e.g. no result.json and no
        progress.json on a side), main() writes a failure artifact and
        exits 2."""
        baseline_dir = tmp_path / "baseline"
        head_dir = tmp_path / "head"
        output = tmp_path / "out" / "comparison.json"
        baseline_dir.mkdir(parents=True)  # empty — no result.json, no progress.json
        _write_driver_result(
            head_dir, _make_driver_payload(revision=_HEAD_SHA)
        )
        exit_code = self._invoke(comparison_module, monkeypatch, [
            "benchmark_comparison.py",
            "--scenario", "20k_activities",
            "--baseline-dir", str(baseline_dir),
            "--head-dir", str(head_dir),
            "--baseline-sha", _BASELINE_SHA,
            "--head-sha", _HEAD_SHA,
            "--tolerance-pct", "10",
            "--output", str(output),
        ])
        assert exit_code == 2
        # Fail-closed: artifact is still written.
        assert output.is_file()
        artifact = json.loads(output.read_text(encoding="utf-8"))
        assert artifact["outcome"] == "both_invalid"
        assert "comparison_error" in artifact

    def test_artifact_always_written_even_on_error(
        self, comparison_module, tmp_path: Path, monkeypatch
    ) -> None:
        """The comparison always writes an artifact, even on input/schema
        errors — the workflow's if: always() upload step relies on this."""
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
            "--baseline-sha", _BASELINE_SHA,
            "--head-sha", _HEAD_SHA,
            "--tolerance-pct", "10",
            "--output", str(output),
        ])
        assert exit_code == 2
        assert output.is_file()
        artifact = json.loads(output.read_text(encoding="utf-8"))
        assert artifact["outcome"] == "both_invalid"
        assert "comparison_error" in artifact

    def test_scenario_required(
        self, comparison_module, tmp_path: Path, monkeypatch
    ) -> None:
        """Omitting --scenario causes argparse to exit with code 2."""
        baseline_dir = tmp_path / "baseline"
        head_dir = tmp_path / "head"
        output = tmp_path / "out" / "comparison.json"
        _write_driver_result(
            baseline_dir, _make_driver_payload(revision=_BASELINE_SHA)
        )
        _write_driver_result(
            head_dir, _make_driver_payload(revision=_HEAD_SHA)
        )
        monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
        monkeypatch.setattr(sys, "argv", [
            "benchmark_comparison.py",
            "--baseline-dir", str(baseline_dir),
            "--head-dir", str(head_dir),
            "--baseline-sha", _BASELINE_SHA,
            "--head-sha", _HEAD_SHA,
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
        _write_driver_result(
            baseline_dir, _make_driver_payload(revision=_BASELINE_SHA)
        )
        _write_driver_result(
            head_dir, _make_driver_payload(revision=_HEAD_SHA)
        )
        monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
        monkeypatch.setattr(sys, "argv", [
            "benchmark_comparison.py",
            "--scenario", "20k_activities",
            "--baseline-dir", str(baseline_dir),
            "--head-dir", str(head_dir),
            "--baseline-sha", _BASELINE_SHA,
            "--head-sha", _HEAD_SHA,
            "--tolerance-pct", "10",
        ])
        with pytest.raises(SystemExit) as exc_info:
            comparison_module.main()
        assert exc_info.value.code == 2
