"""Revision identity validation tests for the WebView comparison layer.

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
import sys
from pathlib import Path
from typing import Any

import pytest

from tests.support.performance_artifact_factory import (
    BASELINE_SHA,
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
# _validate_revision_identity (webview_comparison.py)
# ---------------------------------------------------------------------------

class TestValidateRevisionIdentity:
    """Tests for per-side revision identity validation."""

    def _make_side(
        self,
        comparison_module,
        tmp_path: Path,
        *,
        revision: str,
        actual_target_revision: str,
        expected_sha: str,
    ) -> Any:
        path = write_webview_result(
            tmp_path,
            make_webview_result(
                revision=revision,
                actual_target_revision=actual_target_revision,
            ),
        )
        return comparison_module.SideResult(
            label="baseline",
            artifact_path=path,
            expected_sha=expected_sha,
        )

    def test_missing_requested_revision_raises(
        self, comparison_module, tmp_path: Path
    ) -> None:
        payload = make_webview_result(revision=BASELINE_SHA)
        payload["requested_revision"] = ""
        path = write_webview_result(tmp_path, payload)
        side = comparison_module.SideResult(
            label="baseline", artifact_path=path, expected_sha=BASELINE_SHA,
        )
        with pytest.raises(comparison_module.ComparisonError, match="missing"):
            comparison_module._validate_revision_identity(side)

    def test_missing_actual_target_revision_raises(
        self, comparison_module, tmp_path: Path
    ) -> None:
        payload = make_webview_result(revision=BASELINE_SHA)
        payload["actual_target_revision"] = ""
        path = write_webview_result(tmp_path, payload)
        side = comparison_module.SideResult(
            label="baseline", artifact_path=path, expected_sha=BASELINE_SHA,
        )
        with pytest.raises(comparison_module.ComparisonError, match="missing"):
            comparison_module._validate_revision_identity(side)

    def test_requested_actual_mismatch_raises(
        self, comparison_module, tmp_path: Path
    ) -> None:
        """requested_revision != actual_target_revision means the driver
        did not verify target worktree identity."""
        side = self._make_side(
            comparison_module, tmp_path,
            revision=BASELINE_SHA,
            actual_target_revision=BASELINE_SHA + "deadbeef",
            expected_sha=BASELINE_SHA,
        )
        with pytest.raises(
            comparison_module.ComparisonError, match="requested_revision"
        ):
            comparison_module._validate_revision_identity(side)

    def test_actual_expected_mismatch_raises(
        self, comparison_module, tmp_path: Path
    ) -> None:
        """actual_target_revision must match the expected SHA supplied on the CLI."""
        side = self._make_side(
            comparison_module, tmp_path,
            revision=BASELINE_SHA,
            actual_target_revision=BASELINE_SHA,
            expected_sha="wrongsha",
        )
        with pytest.raises(comparison_module.ComparisonError, match="expected"):
            comparison_module._validate_revision_identity(side)

    def test_matching_revisions_pass(
        self, comparison_module, tmp_path: Path
    ) -> None:
        side = self._make_side(
            comparison_module, tmp_path,
            revision=BASELINE_SHA,
            actual_target_revision=BASELINE_SHA,
            expected_sha=BASELINE_SHA,
        )
        # Should not raise.
        comparison_module._validate_revision_identity(side)

    def test_github_workflow_sha_not_used_for_identity(
        self, comparison_module, tmp_path: Path
    ) -> None:
        """github_workflow_sha may differ from actual_target_revision
        (it can be a merge commit SHA in pull_request workflows) and must
        NOT cause an identity mismatch."""
        path = write_webview_result(
            tmp_path,
            make_webview_result(
                revision=BASELINE_SHA,
                github_workflow_sha="mergecommitsha1234",
            ),
        )
        side = comparison_module.SideResult(
            label="baseline", artifact_path=path, expected_sha=BASELINE_SHA,
        )
        comparison_module._validate_revision_identity(side)
