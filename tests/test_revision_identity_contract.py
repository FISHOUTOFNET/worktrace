"""Contract tests for benchmark revision identity verification.

The HEAD-owned product and WebView drivers must record revision
identity in a way that survives the pull_request workflow's
``GITHUB_SHA`` semantics.  In a ``pull_request`` workflow,
``GITHUB_SHA`` is the *merge commit* SHA, not the PR head SHA —
using it as the target revision would compare the wrong code.

The contract is:

  * ``--revision`` is the requested revision (the PR head SHA resolved
    by the workflow),
  * the driver runs ``git rev-parse HEAD`` inside ``--target-root`` to
    read the *actual* target worktree SHA,
  * the two must match (otherwise the driver exits with code 2),
  * the artifact records both ``requested_revision`` and
    ``actual_target_revision``,
  * ``github_workflow_sha`` is recorded for diagnostics only and is
    never used for identity comparison,
  * the comparison layer fails closed if either artifact's
    requested/actual revisions mismatch internally, or if the actual
    target revision does not match the expected SHA passed on the CLI.

These tests cover both drivers' ``_verify_revision_identity`` helpers
and the comparison layers' ``_validate_revision_identity`` functions.
They use subprocess mocking to avoid actually shelling out to git.
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
PRODUCT_DRIVER_PATH = ROOT / "scripts" / "ci" / "product_benchmark_driver.py"
WEBVIEW_DRIVER_PATH = ROOT / "scripts" / "webview_render_perf.py"
PRODUCT_COMPARISON_PATH = ROOT / "scripts" / "benchmark_comparison.py"
WEBVIEW_COMPARISON_PATH = ROOT / "scripts" / "webview_comparison.py"

_BASELINE_SHA = "a" * 40
_HEAD_SHA = "b" * 40
_MERGE_COMMIT_SHA = "c" * 40  # Simulates GITHUB_SHA in pull_request workflows


# ---------------------------------------------------------------------------
# Module loading fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def product_driver():
    spec = importlib.util.spec_from_file_location(
        "product_driver_revision_under_test", PRODUCT_DRIVER_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["product_driver_revision_under_test"] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop("product_driver_revision_under_test", None)
        raise
    return module


@pytest.fixture(scope="module")
def webview_driver():
    spec = importlib.util.spec_from_file_location(
        "webview_driver_revision_under_test", WEBVIEW_DRIVER_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["webview_driver_revision_under_test"] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop("webview_driver_revision_under_test", None)
        raise
    return module


@pytest.fixture(scope="module")
def product_comparison():
    spec = importlib.util.spec_from_file_location(
        "product_comparison_revision_under_test", PRODUCT_COMPARISON_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["product_comparison_revision_under_test"] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop("product_comparison_revision_under_test", None)
        raise
    return module


@pytest.fixture(scope="module")
def webview_comparison():
    spec = importlib.util.spec_from_file_location(
        "webview_comparison_revision_under_test", WEBVIEW_COMPARISON_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["webview_comparison_revision_under_test"] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop("webview_comparison_revision_under_test", None)
        raise
    return module


# ---------------------------------------------------------------------------
# Driver: _read_actual_target_revision
# ---------------------------------------------------------------------------

class TestProductDriverReadsActualTargetRevision:
    """``product_benchmark_driver._read_actual_target_revision`` must
    shell out to ``git rev-parse HEAD`` inside the target worktree,
    not read ``GITHUB_SHA``."""

    def test_returns_stripped_sha_on_success(
        self, product_driver, tmp_path: Path, monkeypatch
    ) -> None:
        """The function returns the stripped SHA from
        ``git rev-parse HEAD``."""
        captured_cmds: list[list[str]] = []

        def fake_check_output(cmd, **kwargs):
            captured_cmds.append(cmd)
            # Verify it's the right git command.
            assert cmd[:3] == ["git", "rev-parse", "HEAD"]
            assert kwargs.get("cwd") == str(tmp_path)
            return _BASELINE_SHA + "\n"

        monkeypatch.setattr(
            "subprocess.check_output", fake_check_output
        )
        result = product_driver._read_actual_target_revision(tmp_path)
        assert result == _BASELINE_SHA
        assert len(captured_cmds) == 1

    def test_raises_system_exit_2_on_git_failure(
        self, product_driver, tmp_path: Path, monkeypatch
    ) -> None:
        """If ``git rev-parse`` fails, the driver exits with code 2
        (input/schema error), not 3."""
        import subprocess

        def fake_check_output(cmd, **kwargs):
            raise subprocess.CalledProcessError(1, cmd, output=b"")

        monkeypatch.setattr(
            "subprocess.check_output", fake_check_output
        )
        with pytest.raises(SystemExit) as exc_info:
            product_driver._read_actual_target_revision(tmp_path)
        assert exc_info.value.code == product_driver._EXIT_INPUT_SCHEMA

    def test_raises_system_exit_2_on_oserror(
        self, product_driver, tmp_path: Path, monkeypatch
    ) -> None:
        def fake_check_output(cmd, **kwargs):
            raise OSError("git not found")

        monkeypatch.setattr(
            "subprocess.check_output", fake_check_output
        )
        with pytest.raises(SystemExit) as exc_info:
            product_driver._read_actual_target_revision(tmp_path)
        assert exc_info.value.code == product_driver._EXIT_INPUT_SCHEMA

    def test_does_not_read_github_sha(
        self, product_driver, tmp_path: Path, monkeypatch
    ) -> None:
        """The function must NOT consult ``GITHUB_SHA`` — only
        ``git rev-parse HEAD`` on the target worktree."""
        monkeypatch.setenv("GITHUB_SHA", _MERGE_COMMIT_SHA)

        def fake_check_output(cmd, **kwargs):
            return _BASELINE_SHA + "\n"

        monkeypatch.setattr(
            "subprocess.check_output", fake_check_output
        )
        result = product_driver._read_actual_target_revision(tmp_path)
        assert result == _BASELINE_SHA
        assert result != _MERGE_COMMIT_SHA


# ---------------------------------------------------------------------------
# Driver: _verify_revision_identity
# ---------------------------------------------------------------------------

class TestProductDriverVerifyRevisionIdentity:
    """``_verify_revision_identity`` enforces that the requested
    revision matches the actual target worktree SHA."""

    def test_match_returns_actual_sha(
        self, product_driver, tmp_path: Path, monkeypatch
    ) -> None:
        """When ``--revision`` matches the actual target SHA, the
        function returns the actual SHA."""
        monkeypatch.setattr(
            "subprocess.check_output",
            lambda cmd, **kwargs: _BASELINE_SHA + "\n",
        )
        result = product_driver._verify_revision_identity(
            _BASELINE_SHA, tmp_path
        )
        assert result == _BASELINE_SHA

    def test_mismatch_raises_system_exit_2(
        self, product_driver, tmp_path: Path, monkeypatch
    ) -> None:
        """When ``--revision`` does NOT match the actual target SHA,
        the driver exits with code 2 (input/schema error)."""
        monkeypatch.setattr(
            "subprocess.check_output",
            lambda cmd, **kwargs: _HEAD_SHA + "\n",
        )
        with pytest.raises(SystemExit) as exc_info:
            product_driver._verify_revision_identity(
                _BASELINE_SHA, tmp_path
            )
        assert exc_info.value.code == product_driver._EXIT_INPUT_SCHEMA

    def test_mismatch_with_github_sha_does_not_spoof(
        self, product_driver, tmp_path: Path, monkeypatch
    ) -> None:
        """Even if ``GITHUB_SHA`` is set to the requested revision,
        the function still verifies against the actual target SHA —
        so a merge-commit ``GITHUB_SHA`` cannot spoof identity."""
        monkeypatch.setenv("GITHUB_SHA", _BASELINE_SHA)
        monkeypatch.setattr(
            "subprocess.check_output",
            lambda cmd, **kwargs: _HEAD_SHA + "\n",
        )
        with pytest.raises(SystemExit) as exc_info:
            product_driver._verify_revision_identity(
                _BASELINE_SHA, tmp_path
            )
        assert exc_info.value.code == product_driver._EXIT_INPUT_SCHEMA


class TestWebViewDriverVerifyRevisionIdentity:
    """The WebView driver's ``_verify_revision_identity`` must enforce
    the same contract as the product driver's."""

    def test_match_returns_actual_sha(
        self, webview_driver, tmp_path: Path, monkeypatch
    ) -> None:
        monkeypatch.setattr(
            "subprocess.check_output",
            lambda cmd, **kwargs: _BASELINE_SHA + "\n",
        )
        result = webview_driver._verify_revision_identity(
            _BASELINE_SHA, tmp_path
        )
        assert result == _BASELINE_SHA

    def test_mismatch_raises_system_exit_2(
        self, webview_driver, tmp_path: Path, monkeypatch
    ) -> None:
        monkeypatch.setattr(
            "subprocess.check_output",
            lambda cmd, **kwargs: _HEAD_SHA + "\n",
        )
        with pytest.raises(SystemExit) as exc_info:
            webview_driver._verify_revision_identity(
                _BASELINE_SHA, tmp_path
            )
        assert exc_info.value.code == webview_driver._EXIT_INPUT_SCHEMA

    def test_does_not_read_github_sha(
        self, webview_driver, tmp_path: Path, monkeypatch
    ) -> None:
        """The WebView driver must also NOT consult ``GITHUB_SHA``."""
        monkeypatch.setenv("GITHUB_SHA", _MERGE_COMMIT_SHA)
        monkeypatch.setattr(
            "subprocess.check_output",
            lambda cmd, **kwargs: _BASELINE_SHA + "\n",
        )
        result = webview_driver._verify_revision_identity(
            _BASELINE_SHA, tmp_path
        )
        assert result == _BASELINE_SHA
        assert result != _MERGE_COMMIT_SHA


# ---------------------------------------------------------------------------
# Product comparison: _validate_revision_identity
# ---------------------------------------------------------------------------

class TestProductComparisonValidateRevisionIdentity:
    """``benchmark_comparison._validate_revision_identity`` enforces
    the revision identity contract on already-recorded artifacts.

    The new SideResult-based API reads ``result.json`` from an output
    directory, so these tests write synthetic payloads to a temp dir
    and construct a SideResult to pass to ``_validate_revision_identity``.
    """

    def _make_payload(
        self,
        *,
        requested: str = _BASELINE_SHA,
        actual: str | None = None,
        workflow_sha: str | None = None,
    ) -> dict[str, Any]:
        if actual is None:
            actual = requested
        return {
            "schema_version": 3,
            "requested_revision": requested,
            "actual_target_revision": actual,
            "github_workflow_sha": workflow_sha,
            "driver_version": "3.0",
            "fixture_hash": "fixedhash",
            "python_version": "3.11.5",
            "fixture_audit": {
                "scenario": "20k_activities",
                "requested_count": 20000,
                "inserted_count": 20000,
                "preexisting_activity_count": 0,
                "connection_count": 1,
                "commit_count": 41,
            },
            "metrics": {
                "projection_20k_total_seconds": {
                    "samples_seconds": [1.0],
                    "median_seconds": 1.0,
                },
            },
        }

    def _make_side(
        self,
        product_comparison,
        tmp_path: Path,
        *,
        expected_sha: str = _BASELINE_SHA,
        **kwargs,
    ) -> Any:
        """Write a synthetic result.json and return a SideResult."""
        import json as _json
        d = tmp_path / "side"
        d.mkdir(parents=True, exist_ok=True)
        payload = self._make_payload(**kwargs)
        (d / "result.json").write_text(
            _json.dumps(payload), encoding="utf-8"
        )
        return product_comparison.SideResult(
            label="baseline",
            output_dir=d,
            expected_sha=expected_sha,
            scenario="20k_activities",
        )

    def test_match_passes(self, product_comparison, tmp_path: Path) -> None:
        """When requested == actual == expected, validation passes."""
        side = self._make_side(
            product_comparison, tmp_path,
            requested=_BASELINE_SHA, actual=_BASELINE_SHA,
            expected_sha=_BASELINE_SHA,
        )
        product_comparison._validate_revision_identity(side)

    def test_missing_requested_raises(self, product_comparison, tmp_path: Path) -> None:
        side = self._make_side(
            product_comparison, tmp_path,
            requested="", actual=_BASELINE_SHA,
        )
        with pytest.raises(
            product_comparison.ComparisonError, match="missing"
        ):
            product_comparison._validate_revision_identity(side)

    def test_missing_actual_raises(self, product_comparison, tmp_path: Path) -> None:
        side = self._make_side(
            product_comparison, tmp_path,
            requested=_BASELINE_SHA, actual="",
        )
        with pytest.raises(
            product_comparison.ComparisonError, match="missing"
        ):
            product_comparison._validate_revision_identity(side)

    def test_requested_actual_mismatch_raises(
        self, product_comparison, tmp_path: Path
    ) -> None:
        side = self._make_side(
            product_comparison, tmp_path,
            requested=_BASELINE_SHA, actual=_HEAD_SHA,
        )
        with pytest.raises(
            product_comparison.ComparisonError,
            match="requested_revision",
        ):
            product_comparison._validate_revision_identity(side)

    def test_actual_does_not_match_expected_raises(
        self, product_comparison, tmp_path: Path
    ) -> None:
        side = self._make_side(
            product_comparison, tmp_path,
            requested=_BASELINE_SHA, actual=_BASELINE_SHA,
            expected_sha=_HEAD_SHA,
        )
        with pytest.raises(
            product_comparison.ComparisonError, match="expected"
        ):
            product_comparison._validate_revision_identity(side)

    def test_github_workflow_sha_does_not_spoof_identity(
        self, product_comparison, tmp_path: Path
    ) -> None:
        side = self._make_side(
            product_comparison, tmp_path,
            requested=_BASELINE_SHA,
            actual=_BASELINE_SHA,
            workflow_sha=_MERGE_COMMIT_SHA,
        )
        product_comparison._validate_revision_identity(side)

    def test_merge_commit_cannot_spoof_baseline(
        self, product_comparison, tmp_path: Path
    ) -> None:
        side = self._make_side(
            product_comparison, tmp_path,
            requested=_MERGE_COMMIT_SHA,
            actual=_MERGE_COMMIT_SHA,
            workflow_sha=_MERGE_COMMIT_SHA,
            expected_sha=_BASELINE_SHA,
        )
        with pytest.raises(
            product_comparison.ComparisonError, match="expected"
        ):
            product_comparison._validate_revision_identity(side)


# ---------------------------------------------------------------------------
# WebView comparison: _validate_revision_identity
# ---------------------------------------------------------------------------

class TestWebViewComparisonValidateRevisionIdentity:
    """``webview_comparison._validate_revision_identity`` enforces the
    same contract as the product comparison layer."""

    def _make_payload(
        self,
        *,
        requested: str = _BASELINE_SHA,
        actual: str | None = None,
        workflow_sha: str | None = None,
    ) -> dict[str, Any]:
        if actual is None:
            actual = requested
        return {
            "schema_version": 2,
            "requested_revision": requested,
            "actual_target_revision": actual,
            "github_workflow_sha": workflow_sha,
            "status": "ok",
            "driver_version": "2.0",
            "fixture_hash": "fixedhash",
            "python_version": "3.11.5",
            "activity_count": 20000,
            "fixture_audit": {
                "scenario": "webview_render",
                "requested_count": 20000,
                "inserted_count": 20000,
                "preexisting_activity_count": 0,
                "connection_count": 1,
                "commit_count": 41,
            },
            "metrics": {
                "cold_timeline_seconds": {
                    "samples_seconds": [1.0],
                    "median_seconds": 1.0,
                },
                "warm_timeline_seconds": {
                    "samples_seconds": [0.8],
                    "median_seconds": 0.8,
                },
                "detail_payload_seconds": {
                    "samples_seconds": [0.05],
                    "median_seconds": 0.05,
                },
                "detail_total_seconds": {
                    "samples_seconds": [0.2],
                    "median_seconds": 0.2,
                },
            },
        }

    def _make_side(
        self,
        webview_comparison,
        tmp_path: Path,
        *,
        expected_sha: str = _BASELINE_SHA,
        **kwargs,
    ) -> Any:
        """Write a synthetic webview-benchmark.json and return a SideResult."""
        import json as _json
        d = tmp_path / "wv_side"
        d.mkdir(parents=True, exist_ok=True)
        payload = self._make_payload(**kwargs)
        artifact_path = d / "webview-benchmark.json"
        artifact_path.write_text(_json.dumps(payload), encoding="utf-8")
        return webview_comparison.SideResult(
            label="baseline",
            artifact_path=artifact_path,
            expected_sha=expected_sha,
        )

    def test_match_passes(self, webview_comparison, tmp_path: Path) -> None:
        side = self._make_side(
            webview_comparison, tmp_path,
            requested=_BASELINE_SHA, actual=_BASELINE_SHA,
        )
        webview_comparison._validate_revision_identity(side)

    def test_requested_actual_mismatch_raises(
        self, webview_comparison, tmp_path: Path
    ) -> None:
        side = self._make_side(
            webview_comparison, tmp_path,
            requested=_BASELINE_SHA, actual=_HEAD_SHA,
        )
        with pytest.raises(
            webview_comparison.ComparisonError,
            match="requested_revision",
        ):
            webview_comparison._validate_revision_identity(side)

    def test_actual_does_not_match_expected_raises(
        self, webview_comparison, tmp_path: Path
    ) -> None:
        side = self._make_side(
            webview_comparison, tmp_path,
            requested=_BASELINE_SHA, actual=_BASELINE_SHA,
            expected_sha=_HEAD_SHA,
        )
        with pytest.raises(
            webview_comparison.ComparisonError, match="expected"
        ):
            webview_comparison._validate_revision_identity(side)

    def test_github_workflow_sha_does_not_spoof_identity(
        self, webview_comparison, tmp_path: Path
    ) -> None:
        side = self._make_side(
            webview_comparison, tmp_path,
            requested=_BASELINE_SHA,
            actual=_BASELINE_SHA,
            workflow_sha=_MERGE_COMMIT_SHA,
        )
        webview_comparison._validate_revision_identity(side)


# ---------------------------------------------------------------------------
# Workflow SHA diagnostic field preserved in artifact
# ---------------------------------------------------------------------------

class TestWorkflowShaPreservedAsDiagnostic:
    """The artifact must record ``github_workflow_sha`` so reviewers
    can see what ``GITHUB_SHA`` was at measurement time — but the
    field must never be used for identity comparison."""

    def test_product_driver_source_records_github_workflow_sha(
        self,
    ) -> None:
        """The product driver source must include
        ``github_workflow_sha`` in the artifact payload."""
        source = PRODUCT_DRIVER_PATH.read_text(encoding="utf-8")
        assert '"github_workflow_sha"' in source
        assert "os.environ.get(\"GITHUB_SHA\")" in source

    def test_webview_driver_source_records_github_workflow_sha(
        self,
    ) -> None:
        """The WebView driver source must include
        ``github_workflow_sha`` in the artifact payload."""
        source = WEBVIEW_DRIVER_PATH.read_text(encoding="utf-8")
        assert '"github_workflow_sha"' in source
        assert "os.environ.get(\"GITHUB_SHA\")" in source

    def test_product_comparison_preserves_workflow_sha_in_report(
        self, product_comparison
    ) -> None:
        """The comparison report must include ``github_workflow_sha``
        in side diagnostics so the workflow SHA is preserved for
        diagnostics."""
        source = PRODUCT_COMPARISON_PATH.read_text(encoding="utf-8")
        assert "github_workflow_sha" in source

    def test_webview_comparison_preserves_workflow_sha_in_report(
        self, webview_comparison
    ) -> None:
        source = WEBVIEW_COMPARISON_PATH.read_text(encoding="utf-8")
        assert "github_workflow_sha" in source

    def test_product_comparison_does_not_use_workflow_sha_for_identity(
        self, product_comparison
    ) -> None:
        """The comparison source must NOT compare
        ``github_workflow_sha`` against the expected SHA — that would
        let a merge commit spoof identity."""
        source = PRODUCT_COMPARISON_PATH.read_text(encoding="utf-8")
        # _validate_revision_identity must NOT reference github_workflow_sha;
        # find the function body and verify only requested/actual_target_revision.
        func_start = source.find("def _validate_revision_identity(")
        assert func_start != -1, "function not found"
        # Find the next function definition or class.
        func_end = source.find("\ndef ", func_start + 1)
        if func_end == -1:
            func_end = source.find("\nclass ", func_start + 1)
        if func_end == -1:
            func_end = len(source)
        func_body = source[func_start:func_end]
        assert "github_workflow_sha" not in func_body, (
            "_validate_revision_identity must not reference "
            "github_workflow_sha — it can be a merge commit SHA in "
            "pull_request workflows"
        )

    def test_webview_comparison_does_not_use_workflow_sha_for_identity(
        self, webview_comparison
    ) -> None:
        source = WEBVIEW_COMPARISON_PATH.read_text(encoding="utf-8")
        func_start = source.find("def _validate_revision_identity(")
        assert func_start != -1, "function not found"
        func_end = source.find("\ndef ", func_start + 1)
        if func_end == -1:
            func_end = source.find("\nclass ", func_start + 1)
        if func_end == -1:
            func_end = len(source)
        func_body = source[func_start:func_end]
        assert "github_workflow_sha" not in func_body, (
            "_validate_revision_identity must not reference "
            "github_workflow_sha — it can be a merge commit SHA in "
            "pull_request workflows"
        )


# ---------------------------------------------------------------------------
# Cross-check: comparison rejects baseline artifact whose actual_target
# revision is the merge commit SHA
# ---------------------------------------------------------------------------

class TestComparisonRejectsMergeCommitBaseline:
    """End-to-end (synthetic) check: if the baseline artifact's
    ``actual_target_revision`` is the merge commit SHA (GITHUB_SHA),
    but the comparison is asked to validate against the real baseline
    SHA, the comparison must fail closed."""

    def _make_product_payload(
        self, *, revision: str, workflow_sha: str | None = None
    ) -> dict[str, Any]:
        return {
            "schema_version": 3,
            "requested_revision": revision,
            "actual_target_revision": revision,
            "github_workflow_sha": workflow_sha,
            "driver_version": "3.0",
            "fixture_hash": "fixedhash",
            "python_version": "3.11.5",
            "fixture_audit": {
                "scenario": "20k_activities",
                "requested_count": 20000,
                "inserted_count": 20000,
                "preexisting_activity_count": 0,
                "connection_count": 1,
                "commit_count": 41,
            },
            "metrics": {
                "projection_20k_total_seconds": {
                    "samples_seconds": [1.0, 1.05, 0.98],
                    "median_seconds": 1.0,
                    "consistency_hash": "hash_large",
                },
            },
        }

    def test_baseline_with_merge_commit_sha_rejected(
        self, product_comparison, tmp_path: Path
    ) -> None:
        """If the baseline artifact's actual_target_revision is the
        merge commit SHA, the comparison must reject it because the
        expected baseline SHA is the real PR head."""
        baseline_payload = self._make_product_payload(
            revision=_MERGE_COMMIT_SHA,
            workflow_sha=_MERGE_COMMIT_SHA,
        )
        head_payload = self._make_product_payload(
            revision=_HEAD_SHA,
            workflow_sha=_MERGE_COMMIT_SHA,
        )
        baseline_dir = tmp_path / "baseline"
        head_dir = tmp_path / "head"
        baseline_dir.mkdir()
        head_dir.mkdir()
        (baseline_dir / "result.json").write_text(
            json.dumps(baseline_payload), encoding="utf-8"
        )
        (head_dir / "result.json").write_text(
            json.dumps(head_payload), encoding="utf-8"
        )

        # The new _build_comparison is keyword-only and scenario-scoped.
        # It captures consistency errors into the artifact rather than
        # raising, so we check the artifact's outcome instead.
        report = product_comparison._build_comparison(
            scenario="20k_activities",
            baseline_dir=baseline_dir,
            head_dir=head_dir,
            baseline_sha=_BASELINE_SHA,  # the REAL baseline
            head_sha=_HEAD_SHA,
            tolerance_pct=10.0,
        )
        assert report["outcome"] != "comparison_passed"

    def test_baseline_with_correct_sha_accepted(
        self, product_comparison, tmp_path: Path
    ) -> None:
        """When the baseline artifact's actual_target_revision matches
        the expected baseline SHA, the comparison proceeds."""
        baseline_payload = self._make_product_payload(
            revision=_BASELINE_SHA,
            workflow_sha=_MERGE_COMMIT_SHA,  # may differ — diagnostic only
        )
        head_payload = self._make_product_payload(
            revision=_HEAD_SHA,
            workflow_sha=_MERGE_COMMIT_SHA,
        )
        baseline_dir = tmp_path / "baseline"
        head_dir = tmp_path / "head"
        baseline_dir.mkdir()
        head_dir.mkdir()
        (baseline_dir / "result.json").write_text(
            json.dumps(baseline_payload), encoding="utf-8"
        )
        (head_dir / "result.json").write_text(
            json.dumps(head_payload), encoding="utf-8"
        )

        report = product_comparison._build_comparison(
            scenario="20k_activities",
            baseline_dir=baseline_dir,
            head_dir=head_dir,
            baseline_sha=_BASELINE_SHA,
            head_sha=_HEAD_SHA,
            tolerance_pct=10.0,
        )
        assert report["baseline_sha"] == _BASELINE_SHA
        assert report["head_sha"] == _HEAD_SHA
        # The workflow SHA is preserved in side diagnostics.
        baseline_diag = report.get("baseline", {})
        assert baseline_diag.get("github_workflow_sha") == _MERGE_COMMIT_SHA
