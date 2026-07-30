"""Unit tests for the Standard timing validation comparison layer.

Covers the pure-Python functions in ``scripts/timing_comparison.py``:
prepare-mode set computation, manifest validation, compare-mode gate
logic (common-suite 10% regression gate, full-HEAD 240s gate,
HEAD-only gate, dependency-match gate, all-runs-valid gate), and
fail-closed exit-code semantics.

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
SCRIPT_PATH = ROOT / "scripts" / "timing_comparison.py"

_BASELINE_SHA = "a" * 40
_HEAD_SHA = "b" * 40


# ---------------------------------------------------------------------------
# Module loading fixture
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def tc():
    """Load scripts/timing_comparison.py as a module."""
    spec = importlib.util.spec_from_file_location(
        "timing_comparison_under_test", SCRIPT_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["timing_comparison_under_test"] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop("timing_comparison_under_test", None)
        raise
    return module


# ---------------------------------------------------------------------------
# Helpers for building synthetic timing results
# ---------------------------------------------------------------------------

def _make_timing_payload(
    *,
    revision: str,
    tests: list[dict[str, Any]] | None = None,
    schema_version: int = 1,
    selection_hash: str = "",
    selected_count: int = 0,
    collected_count: int = 0,
    exit_code: int = 0,
    marker_expression: str = "not benchmark",
    worker_count: int = 0,
) -> dict[str, Any]:
    """Build a synthetic timing.json payload."""
    if tests is None:
        tests = []
    return {
        "schema_version": schema_version,
        "revision": revision,
        "worktree_root": "/tmp/worktree",
        "plugin_path": "/tmp/.ci-harness/pytest_timing_plugin.py",
        "selection_hash": selection_hash,
        "python_version": "3.11.5",
        "pytest_version": "8.0.0",
        "worker_count": worker_count,
        "marker_expression": marker_expression,
        "selected_count": selected_count,
        "collected_count": collected_count,
        "deselected_count": max(0, collected_count - selected_count),
        "started_at": "2026-07-15T00:00:00.000000Z",
        "finished_at": "2026-07-15T00:01:00.000000Z",
        "exit_code": exit_code,
        "tests": tests,
    }


def _make_run_result(
    *,
    elapsed_seconds: float = 10.0,
    exit_code: int = 0,
    test_count: int = 5,
    failure_count: int = 0,
    error_count: int = 0,
    skipped_count: int = 0,
    valid: bool = True,
) -> dict[str, Any]:
    """Build a synthetic run-result.json payload."""
    return {
        "elapsed_seconds": elapsed_seconds,
        "exit_code": exit_code,
        "test_count": test_count,
        "failure_count": failure_count,
        "error_count": error_count,
        "skipped_count": skipped_count,
        "valid": valid,
    }


def _make_test_entry(
    nodeid: str,
    *,
    total_seconds: float = 0.1,
    outcome: str = "passed",
) -> dict[str, Any]:
    return {
        "nodeid": nodeid,
        "setup_seconds": 0.01,
        "call_seconds": total_seconds - 0.03,
        "teardown_seconds": 0.02,
        "total_seconds": total_seconds,
        "outcome": outcome,
    }


def _write_json(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def _write_lines(path: Path, lines: list[str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Pure-function tests: _read_id_file
# ---------------------------------------------------------------------------

class TestReadIdFile:
    """Tests for reading and validating a collection / node-ID file."""

    def test_reads_ids_stripping_whitespace(self, tc, tmp_path: Path) -> None:
        path = _write_lines(tmp_path / "ids.txt", [
            "tests/test_a.py::test_one",
            "  tests/test_a.py::test_two  ",
            "tests/test_b.py::TestClass::test_method",
        ])
        ids = tc._read_id_file(path)
        assert ids == {
            "tests/test_a.py::test_one",
            "tests/test_a.py::test_two",
            "tests/test_b.py::TestClass::test_method",
        }

    def test_ignores_comments_and_blank_lines(self, tc, tmp_path: Path) -> None:
        path = _write_lines(tmp_path / "ids.txt", [
            "# This is a comment",
            "",
            "tests/test_a.py::test_one",
            "# Another comment",
            "tests/test_a.py::test_two",
        ])
        ids = tc._read_id_file(path)
        assert ids == {"tests/test_a.py::test_one", "tests/test_a.py::test_two"}

    def test_missing_file_raises_validation_error(
        self, tc, tmp_path: Path
    ) -> None:
        with pytest.raises(tc.ValidationError, match="collection file missing"):
            tc._read_id_file(tmp_path / "nonexistent.txt")

    def test_duplicate_ids_raise_validation_error(
        self, tc, tmp_path: Path
    ) -> None:
        path = _write_lines(tmp_path / "ids.txt", [
            "tests/test_a.py::test_one",
            "tests/test_a.py::test_one",
        ])
        with pytest.raises(tc.ValidationError, match="duplicate node IDs"):
            tc._read_id_file(path)

    def test_empty_file_returns_empty_set(
        self, tc, tmp_path: Path
    ) -> None:
        """An empty collection file (no IDs) is not an error at the
        read level — the prepare layer decides whether an empty common
        set is a failure."""
        path = _write_lines(tmp_path / "ids.txt", [])
        assert tc._read_id_file(path) == set()


# ---------------------------------------------------------------------------
# Pure-function tests: _floor_median
# ---------------------------------------------------------------------------

class TestFloorMedian:
    """Tests for the floor-based median (matches PowerShell [math]::Floor)."""

    def test_empty_returns_zero(self, tc) -> None:
        assert tc._floor_median([]) == 0.0

    def test_single_element(self, tc) -> None:
        assert tc._floor_median([5.0]) == 5.0

    def test_three_elements_returns_middle(self, tc) -> None:
        # sorted: [1, 3, 5], idx = (3-1)//2 = 1 → 3
        assert tc._floor_median([3.0, 1.0, 5.0]) == 3.0

    def test_two_elements_returns_lower_middle(self, tc) -> None:
        # sorted: [2, 4], idx = (2-1)//2 = 0 → 2
        assert tc._floor_median([2.0, 4.0]) == 2.0

    def test_four_elements_returns_lower_middle(self, tc) -> None:
        # sorted: [1, 2, 3, 4], idx = (4-1)//2 = 1 → 2
        assert tc._floor_median([1.0, 2.0, 3.0, 4.0]) == 2.0


# ---------------------------------------------------------------------------
# Pure-function tests: _percent, _module_of
# ---------------------------------------------------------------------------

class TestPercent:
    """Tests for the percentage helper."""

    def test_zero_whole_returns_zero(self, tc) -> None:
        assert tc._percent(5.0, 0.0) == 0.0

    def test_normal_computation(self, tc) -> None:
        assert tc._percent(1.0, 10.0) == 10.0

    def test_negative_part(self, tc) -> None:
        assert tc._percent(-2.0, 10.0) == -20.0


class TestModuleOf:
    """Tests for extracting the module path from a pytest node ID."""

    def test_simple_function(self, tc) -> None:
        assert tc._module_of("tests/test_a.py::test_one") == "tests/test_a.py"

    def test_class_method(self, tc) -> None:
        # _module_of splits on the LAST "::", so a class-method node ID
        # maps to the class-qualified path, not just the file path.
        assert (
            tc._module_of("tests/test_b.py::TestClass::test_method")
            == "tests/test_b.py::TestClass"
        )

    def test_parametrized(self, tc) -> None:
        assert (
            tc._module_of("tests/test_c.py::test_param[1-2]")
            == "tests/test_c.py"
        )


# ---------------------------------------------------------------------------
# Pure-function tests: _sha256_of_ids, _sha256_of_file
# ---------------------------------------------------------------------------

class TestSha256Helpers:
    """Tests for the hashing helpers."""

    def test_sha256_of_ids_is_deterministic_and_sorted(self, tc) -> None:
        ids_a = {"b", "a", "c"}
        ids_b = {"c", "a", "b"}
        assert tc._sha256_of_ids(ids_a) == tc._sha256_of_ids(ids_b)

    def test_sha256_of_ids_differs_for_different_sets(self, tc) -> None:
        assert tc._sha256_of_ids({"a"}) != tc._sha256_of_ids({"b"})

    def test_sha256_of_file_returns_empty_for_missing(self, tc, tmp_path: Path) -> None:
        assert tc._sha256_of_file(tmp_path / "nonexistent.txt") == ""

    def test_sha256_of_file_returns_hash_for_existing(
        self, tc, tmp_path: Path
    ) -> None:
        path = tmp_path / "file.txt"
        path.write_text("hello\n", encoding="utf-8")
        h = tc._sha256_of_file(path)
        assert len(h) == 64
        assert h != ""


# ---------------------------------------------------------------------------
# Prepare mode tests
# ---------------------------------------------------------------------------

def _build_collection_dir(
    results_dir: Path,
    *,
    baseline_ids: list[str],
    head_ids: list[str],
) -> Path:
    """Create the collection/ directory with baseline and HEAD node-ID files."""
    coll = results_dir / "collection"
    coll.mkdir(parents=True, exist_ok=True)
    _write_lines(coll / "baseline-node-ids.txt", baseline_ids)
    _write_lines(coll / "head-node-ids.txt", head_ids)
    return coll


def _run_prepare(
    tc,
    results_dir: Path,
    *,
    baseline_sha: str = _BASELINE_SHA,
    head_sha: str = _HEAD_SHA,
    dependency_match: str = "true",
) -> int:
    """Invoke the prepare mode via _run_prepare with a synthetic Namespace."""
    import argparse
    args = argparse.Namespace(
        results_dir=results_dir,
        baseline_sha=baseline_sha,
        head_sha=head_sha,
        dependency_match=dependency_match,
        write_selection_only=True,
        compare=False,
        common_regression_threshold_pct=10.0,
        head_full_limit_seconds=240.0,
    )
    return tc._run_prepare(args)


class TestPrepareMode:
    """Tests for the --write-selection-only (prepare) mode."""

    def test_prepare_writes_common_head_only_baseline_only(
        self, tc, tmp_path: Path
    ) -> None:
        results = tmp_path / "results"
        _build_collection_dir(
            results,
            baseline_ids=[
                "tests/test_a.py::test_one",
                "tests/test_a.py::test_two",
                "tests/test_b.py::test_only_baseline",
            ],
            head_ids=[
                "tests/test_a.py::test_one",
                "tests/test_a.py::test_two",
                "tests/test_c.py::test_only_head",
            ],
        )
        exit_code = _run_prepare(tc, results)
        assert exit_code == 0

        selection = results / "selection"
        common = (selection / "common.txt").read_text(encoding="utf-8").splitlines()
        head_only = (selection / "head-only.txt").read_text(encoding="utf-8").splitlines()
        baseline_only = (selection / "baseline-only.txt").read_text(encoding="utf-8").splitlines()

        assert set(common) == {
            "tests/test_a.py::test_one",
            "tests/test_a.py::test_two",
        }
        assert set(head_only) == {"tests/test_c.py::test_only_head"}
        assert set(baseline_only) == {"tests/test_b.py::test_only_baseline"}

    def test_prepare_writes_manifest_with_correct_counts(
        self, tc, tmp_path: Path
    ) -> None:
        results = tmp_path / "results"
        _build_collection_dir(
            results,
            baseline_ids=[
                "tests/test_a.py::test_one",
                "tests/test_a.py::test_two",
                "tests/test_b.py::test_only_baseline",
            ],
            head_ids=[
                "tests/test_a.py::test_one",
                "tests/test_a.py::test_two",
                "tests/test_c.py::test_only_head",
            ],
        )
        exit_code = _run_prepare(tc, results)
        assert exit_code == 0

        manifest = json.loads(
            (results / "selection" / "manifest.json").read_text(encoding="utf-8")
        )
        assert manifest["schema_version"] == 1
        assert manifest["baseline_sha"] == _BASELINE_SHA
        assert manifest["head_sha"] == _HEAD_SHA
        assert manifest["baseline_collected"] == 3
        assert manifest["head_collected"] == 3
        assert manifest["common_count"] == 2
        assert manifest["head_only_count"] == 1
        assert manifest["baseline_only_count"] == 1
        assert manifest["common_selection_hash"] != ""
        assert manifest["head_only_selection_hash"] != ""
        assert manifest["common_selection_file_hash"] != ""
        assert manifest["head_only_selection_file_hash"] != ""
        assert manifest["dependency_match"] is True

    def test_prepare_empty_common_set_fails(
        self, tc, tmp_path: Path
    ) -> None:
        """If baseline and HEAD share no tests, prepare must fail (exit 2)."""
        results = tmp_path / "results"
        _build_collection_dir(
            results,
            baseline_ids=["tests/test_a.py::test_one"],
            head_ids=["tests/test_b.py::test_two"],
        )
        exit_code = _run_prepare(tc, results)
        assert exit_code == tc._EXIT_INPUT_SCHEMA

    def test_prepare_missing_baseline_collection_fails(
        self, tc, tmp_path: Path
    ) -> None:
        results = tmp_path / "results"
        coll = results / "collection"
        coll.mkdir(parents=True, exist_ok=True)
        _write_lines(coll / "head-node-ids.txt", ["tests/test_a.py::test_one"])
        exit_code = _run_prepare(tc, results)
        assert exit_code == tc._EXIT_INPUT_SCHEMA

    def test_prepare_missing_head_collection_fails(
        self, tc, tmp_path: Path
    ) -> None:
        results = tmp_path / "results"
        coll = results / "collection"
        coll.mkdir(parents=True, exist_ok=True)
        _write_lines(coll / "baseline-node-ids.txt", ["tests/test_a.py::test_one"])
        exit_code = _run_prepare(tc, results)
        assert exit_code == tc._EXIT_INPUT_SCHEMA

    def test_prepare_duplicate_in_baseline_fails(
        self, tc, tmp_path: Path
    ) -> None:
        results = tmp_path / "results"
        _build_collection_dir(
            results,
            baseline_ids=[
                "tests/test_a.py::test_one",
                "tests/test_a.py::test_one",
            ],
            head_ids=["tests/test_a.py::test_one"],
        )
        exit_code = _run_prepare(tc, results)
        assert exit_code == tc._EXIT_INPUT_SCHEMA

    def test_prepare_no_head_only_tests_succeeds(
        self, tc, tmp_path: Path
    ) -> None:
        """If HEAD is a subset of baseline (head-only is empty), prepare
        succeeds — the head-only file is empty but that's valid."""
        results = tmp_path / "results"
        _build_collection_dir(
            results,
            baseline_ids=[
                "tests/test_a.py::test_one",
                "tests/test_a.py::test_two",
            ],
            head_ids=["tests/test_a.py::test_one"],
        )
        exit_code = _run_prepare(tc, results)
        assert exit_code == 0
        head_only = (results / "selection" / "head-only.txt").read_text(
            encoding="utf-8"
        )
        assert head_only == ""

    def test_prepare_manifest_dependency_match_false(
        self, tc, tmp_path: Path
    ) -> None:
        results = tmp_path / "results"
        _build_collection_dir(
            results,
            baseline_ids=["tests/test_a.py::test_one"],
            head_ids=["tests/test_a.py::test_one"],
        )
        exit_code = _run_prepare(tc, results, dependency_match="false")
        assert exit_code == 0
        manifest = json.loads(
            (results / "selection" / "manifest.json").read_text(encoding="utf-8")
        )
        assert manifest["dependency_match"] is False


# ---------------------------------------------------------------------------
# Compare mode: loading and validation helpers
# ---------------------------------------------------------------------------

class TestLoadTimingJson:
    """Tests for _load_timing_json fail-closed behavior."""

    def test_missing_file_raises_validation_error(
        self, tc, tmp_path: Path
    ) -> None:
        with pytest.raises(tc.ValidationError, match="timing.json missing"):
            tc._load_timing_json(tmp_path / "timing.json")

    def test_invalid_json_raises_validation_error(
        self, tc, tmp_path: Path
    ) -> None:
        path = tmp_path / "timing.json"
        path.write_text("{not valid", encoding="utf-8")
        with pytest.raises(tc.ValidationError, match="cannot parse"):
            tc._load_timing_json(path)

    def test_wrong_schema_version_raises_validation_error(
        self, tc, tmp_path: Path
    ) -> None:
        path = _write_json(
            tmp_path / "timing.json",
            _make_timing_payload(revision=_HEAD_SHA, schema_version=99),
        )
        with pytest.raises(tc.ValidationError, match="schema_version"):
            tc._load_timing_json(path)

    def test_valid_payload_returns_dict(
        self, tc, tmp_path: Path
    ) -> None:
        path = _write_json(
            tmp_path / "timing.json",
            _make_timing_payload(revision=_HEAD_SHA),
        )
        result = tc._load_timing_json(path)
        assert result["revision"] == _HEAD_SHA


class TestValidateTimingPayload:
    """Tests for _validate_timing_payload consistency checks."""

    def test_revision_mismatch_raises_validation_error(self, tc) -> None:
        payload = _make_timing_payload(revision="wrong")
        with pytest.raises(tc.ValidationError, match="revision"):
            tc._validate_timing_payload(
                payload,
                expected_revision=_HEAD_SHA,
                expected_selection_hash="",
                expected_selected_count=None,
                label="test",
            )

    def test_selection_hash_mismatch_raises_validation_error(self, tc) -> None:
        payload = _make_timing_payload(
            revision=_HEAD_SHA, selection_hash="wrong"
        )
        with pytest.raises(tc.ValidationError, match="selection_hash"):
            tc._validate_timing_payload(
                payload,
                expected_revision=_HEAD_SHA,
                expected_selection_hash="expected",
                expected_selected_count=None,
                label="test",
            )

    def test_nonzero_exit_code_raises_incomplete_run_error(self, tc) -> None:
        payload = _make_timing_payload(revision=_HEAD_SHA, exit_code=1)
        with pytest.raises(tc.IncompleteRunError, match="exit_code"):
            tc._validate_timing_payload(
                payload,
                expected_revision=_HEAD_SHA,
                expected_selection_hash="",
                expected_selected_count=None,
                label="test",
            )

    def test_failed_test_raises_incomplete_run_error(self, tc) -> None:
        payload = _make_timing_payload(
            revision=_HEAD_SHA,
            tests=[_make_test_entry("tests/test_a.py::test_one", outcome="failed")],
        )
        with pytest.raises(tc.IncompleteRunError, match="failed"):
            tc._validate_timing_payload(
                payload,
                expected_revision=_HEAD_SHA,
                expected_selection_hash="",
                expected_selected_count=None,
                label="test",
            )

    def test_selected_count_mismatch_raises_incomplete_run_error(self, tc) -> None:
        payload = _make_timing_payload(
            revision=_HEAD_SHA, selected_count=10
        )
        with pytest.raises(tc.IncompleteRunError, match="selected_count"):
            tc._validate_timing_payload(
                payload,
                expected_revision=_HEAD_SHA,
                expected_selection_hash="",
                expected_selected_count=5,
                label="test",
            )

    def test_valid_payload_passes(self, tc) -> None:
        payload = _make_timing_payload(
            revision=_HEAD_SHA,
            selection_hash="abc",
            selected_count=5,
        )
        tc._validate_timing_payload(
            payload,
            expected_revision=_HEAD_SHA,
            expected_selection_hash="abc",
            expected_selected_count=5,
            label="test",
        )

    def test_none_selection_hash_skips_check(self, tc) -> None:
        """When expected_selection_hash is None (full-suite runs), the
        selection_hash check is skipped — full-suite runs have no
        selection file."""
        payload = _make_timing_payload(
            revision=_HEAD_SHA, selection_hash=""
        )
        tc._validate_timing_payload(
            payload,
            expected_revision=_HEAD_SHA,
            expected_selection_hash=None,
            expected_selected_count=None,
            label="test",
        )

    def test_none_selected_count_skips_check(self, tc) -> None:
        """When expected_selected_count is None, the count check is skipped."""
        payload = _make_timing_payload(
            revision=_HEAD_SHA, selected_count=999
        )
        tc._validate_timing_payload(
            payload,
            expected_revision=_HEAD_SHA,
            expected_selection_hash="",
            expected_selected_count=None,
            label="test",
        )


# ---------------------------------------------------------------------------
# Compare mode: _load_pair and _load_simple_run
# ---------------------------------------------------------------------------

class TestLoadPair:
    """Tests for loading a common-suite pair (baseline + HEAD)."""

    def _setup_pair(
        self,
        results_dir: Path,
        *,
        pair_index: int,
        baseline_timing: dict[str, Any],
        head_timing: dict[str, Any],
        baseline_result: dict[str, Any] | None = None,
        head_result: dict[str, Any] | None = None,
    ) -> Path:
        pair_dir = results_dir / f"pair-{pair_index}"
        b_dir = pair_dir / "baseline"
        h_dir = pair_dir / "head"
        _write_json(b_dir / "timing.json", baseline_timing)
        _write_json(h_dir / "timing.json", head_timing)
        _write_json(
            b_dir / "run-result.json",
            baseline_result or _make_run_result(test_count=3),
        )
        _write_json(
            h_dir / "run-result.json",
            head_result or _make_run_result(test_count=3),
        )
        return pair_dir

    def test_valid_pair_returns_dict(self, tc, tmp_path: Path) -> None:
        results = tmp_path / "results"
        common_hash = "abc123"
        self._setup_pair(
            results,
            pair_index=1,
            baseline_timing=_make_timing_payload(
                revision=_BASELINE_SHA,
                selection_hash=common_hash,
                selected_count=3,
            ),
            head_timing=_make_timing_payload(
                revision=_HEAD_SHA,
                selection_hash=common_hash,
                selected_count=3,
            ),
        )
        pair = tc._load_pair(
            results,
            1,
            baseline_sha=_BASELINE_SHA,
            head_sha=_HEAD_SHA,
            common_selection_hash=common_hash,
            common_count=3,
        )
        assert pair["pair"] == 1
        assert pair["baseline_exit_code"] == 0
        assert pair["head_exit_code"] == 0

    def test_zero_wall_clock_raises_incomplete(self, tc, tmp_path: Path) -> None:
        results = tmp_path / "results"
        common_hash = "abc123"
        self._setup_pair(
            results,
            pair_index=1,
            baseline_timing=_make_timing_payload(
                revision=_BASELINE_SHA,
                selection_hash=common_hash,
                selected_count=3,
            ),
            head_timing=_make_timing_payload(
                revision=_HEAD_SHA,
                selection_hash=common_hash,
                selected_count=3,
            ),
            baseline_result=_make_run_result(elapsed_seconds=0.0),
        )
        with pytest.raises(tc.IncompleteRunError, match="elapsed_seconds"):
            tc._load_pair(
                results,
                1,
                baseline_sha=_BASELINE_SHA,
                head_sha=_HEAD_SHA,
                common_selection_hash=common_hash,
                common_count=3,
            )

    def test_nonzero_exit_in_run_result_raises_incomplete(
        self, tc, tmp_path: Path
    ) -> None:
        results = tmp_path / "results"
        common_hash = "abc123"
        self._setup_pair(
            results,
            pair_index=1,
            baseline_timing=_make_timing_payload(
                revision=_BASELINE_SHA,
                selection_hash=common_hash,
                selected_count=3,
            ),
            head_timing=_make_timing_payload(
                revision=_HEAD_SHA,
                selection_hash=common_hash,
                selected_count=3,
            ),
            baseline_result=_make_run_result(exit_code=1),
        )
        with pytest.raises(tc.IncompleteRunError, match="exit codes"):
            tc._load_pair(
                results,
                1,
                baseline_sha=_BASELINE_SHA,
                head_sha=_HEAD_SHA,
                common_selection_hash=common_hash,
                common_count=3,
            )

    def test_failures_in_run_result_raises_incomplete(
        self, tc, tmp_path: Path
    ) -> None:
        results = tmp_path / "results"
        common_hash = "abc123"
        self._setup_pair(
            results,
            pair_index=1,
            baseline_timing=_make_timing_payload(
                revision=_BASELINE_SHA,
                selection_hash=common_hash,
                selected_count=3,
            ),
            head_timing=_make_timing_payload(
                revision=_HEAD_SHA,
                selection_hash=common_hash,
                selected_count=3,
            ),
            head_result=_make_run_result(failure_count=2),
        )
        with pytest.raises(tc.IncompleteRunError, match="failures"):
            tc._load_pair(
                results,
                1,
                baseline_sha=_BASELINE_SHA,
                head_sha=_HEAD_SHA,
                common_selection_hash=common_hash,
                common_count=3,
            )


class TestLoadSimpleRun:
    """Tests for loading a single (non-pair) run — HEAD-only or HEAD-full."""

    def test_valid_run_returns_dict(self, tc, tmp_path: Path) -> None:
        run_dir = tmp_path / "head-only" / "run-1"
        _write_json(
            run_dir / "timing.json",
            _make_timing_payload(
                revision=_HEAD_SHA,
                selection_hash="ho_hash",
                selected_count=2,
            ),
        )
        _write_json(
            run_dir / "run-result.json",
            _make_run_result(test_count=2),
        )
        run = tc._load_simple_run(
            run_dir,
            expected_revision=_HEAD_SHA,
            expected_selection_hash="ho_hash",
            expected_selected_count=2,
            label="head-only/run-1",
        )
        assert run["wall_seconds"] == 10.0
        assert run["test_count"] == 2

    def test_zero_wall_raises_incomplete(self, tc, tmp_path: Path) -> None:
        run_dir = tmp_path / "head-only" / "run-1"
        _write_json(
            run_dir / "timing.json",
            _make_timing_payload(revision=_HEAD_SHA, selection_hash=""),
        )
        _write_json(
            run_dir / "run-result.json",
            _make_run_result(elapsed_seconds=0.0),
        )
        with pytest.raises(tc.IncompleteRunError, match="elapsed_seconds"):
            tc._load_simple_run(
                run_dir,
                expected_revision=_HEAD_SHA,
                expected_selection_hash="",
                expected_selected_count=None,
                label="head-only/run-1",
            )

    def test_missing_timing_json_raises_validation(
        self, tc, tmp_path: Path
    ) -> None:
        run_dir = tmp_path / "head-only" / "run-1"
        run_dir.mkdir(parents=True)
        _write_json(
            run_dir / "run-result.json",
            _make_run_result(),
        )
        with pytest.raises(tc.ValidationError, match="timing.json missing"):
            tc._load_simple_run(
                run_dir,
                expected_revision=_HEAD_SHA,
                expected_selection_hash="",
                expected_selected_count=None,
                label="head-only/run-1",
            )


# ---------------------------------------------------------------------------
# Compare mode: full _build_comparison with gates
# ---------------------------------------------------------------------------

def _setup_full_comparison(
    results_dir: Path,
    *,
    baseline_walls: list[float],
    head_walls: list[float],
    head_full_walls: list[float],
    head_only_walls: list[float] | None = None,
    common_count: int = 3,
    head_only_count: int = 0,
    common_hash: str = "common_hash",
    head_only_hash: str = "head_only_hash",
    common_tests: list[dict[str, Any]] | None = None,
    head_full_test_count: int = 100,
    dependency_match: str = "true",
) -> None:
    """Build a complete results directory with all 3 pairs, HEAD-only, HEAD-full,
    and the selection manifest for compare mode."""
    # ---- Collection ----
    coll = results_dir / "collection"
    coll.mkdir(parents=True, exist_ok=True)
    baseline_ids = [f"tests/test_a.py::test_{i}" for i in range(common_count)]
    head_ids = list(baseline_ids)
    if head_only_count > 0:
        head_ids += [
            f"tests/test_ho.py::test_{i}" for i in range(head_only_count)
        ]
    _write_lines(coll / "baseline-node-ids.txt", baseline_ids)
    _write_lines(coll / "head-node-ids.txt", head_ids)

    # ---- Selection manifest ----
    selection = results_dir / "selection"
    selection.mkdir(parents=True, exist_ok=True)
    common_ids = set(baseline_ids)
    head_only_ids = set(head_ids) - common_ids
    _write_lines(selection / "common.txt", sorted(common_ids))
    _write_lines(selection / "head-only.txt", sorted(head_only_ids))
    _write_lines(selection / "baseline-only.txt", [])

    if common_tests is None:
        common_tests = [
            _make_test_entry(nid, total_seconds=0.1) for nid in sorted(common_ids)
        ]

    manifest = {
        "schema_version": 1,
        "baseline_sha": _BASELINE_SHA,
        "head_sha": _HEAD_SHA,
        "dependency_match": dependency_match == "true",
        "baseline_collected": len(baseline_ids),
        "head_collected": len(head_ids),
        "common_count": common_count,
        "head_only_count": head_only_count,
        "baseline_only_count": 0,
        "common_selection_hash": "unused",
        "head_only_selection_hash": "unused",
        "common_selection_file_hash": common_hash,
        "head_only_selection_file_hash": head_only_hash,
    }
    _write_json(selection / "manifest.json", manifest)

    # ---- 3 pairs ----
    for i in range(3):
        pair_dir = results_dir / f"pair-{i + 1}"
        b_dir = pair_dir / "baseline"
        h_dir = pair_dir / "head"
        _write_json(
            b_dir / "timing.json",
            _make_timing_payload(
                revision=_BASELINE_SHA,
                selection_hash=common_hash,
                selected_count=common_count,
                collected_count=common_count,
                tests=common_tests,
            ),
        )
        _write_json(
            h_dir / "timing.json",
            _make_timing_payload(
                revision=_HEAD_SHA,
                selection_hash=common_hash,
                selected_count=common_count,
                collected_count=common_count,
                tests=common_tests,
            ),
        )
        _write_json(
            b_dir / "run-result.json",
            _make_run_result(
                elapsed_seconds=baseline_walls[i], test_count=common_count
            ),
        )
        _write_json(
            h_dir / "run-result.json",
            _make_run_result(
                elapsed_seconds=head_walls[i], test_count=common_count
            ),
        )

    # ---- HEAD-only runs (only if head_only_count > 0) ----
    if head_only_count > 0:
        ho_walls = head_only_walls or [5.0, 5.0, 5.0]
        ho_tests = [
            _make_test_entry(nid, total_seconds=0.1)
            for nid in sorted(head_only_ids)
        ]
        for i in range(3):
            run_dir = results_dir / "head-only" / f"run-{i + 1}"
            _write_json(
                run_dir / "timing.json",
                _make_timing_payload(
                    revision=_HEAD_SHA,
                    selection_hash=head_only_hash,
                    selected_count=head_only_count,
                    collected_count=head_only_count,
                    tests=ho_tests,
                ),
            )
            _write_json(
                run_dir / "run-result.json",
                _make_run_result(
                    elapsed_seconds=ho_walls[i], test_count=head_only_count
                ),
            )

    # ---- HEAD-full runs ----
    for i in range(3):
        run_dir = results_dir / "head-full" / f"run-{i + 1}"
        _write_json(
            run_dir / "timing.json",
            _make_timing_payload(
                revision=_HEAD_SHA,
                selection_hash="",
                selected_count=head_full_test_count,
                collected_count=head_full_test_count,
                tests=[
                    _make_test_entry(f"tests/test_f.py::test_{j}")
                    for j in range(min(5, head_full_test_count))
                ],
            ),
        )
        _write_json(
            run_dir / "run-result.json",
            _make_run_result(
                elapsed_seconds=head_full_walls[i],
                test_count=head_full_test_count,
            ),
        )


class TestBuildComparisonGates:
    """Tests for the full _build_comparison gate logic."""

    def test_all_gates_pass_when_no_regression(
        self, tc, tmp_path: Path
    ) -> None:
        results = tmp_path / "results"
        _setup_full_comparison(
            results,
            baseline_walls=[100.0, 100.0, 100.0],
            head_walls=[100.0, 100.0, 100.0],
            head_full_walls=[200.0, 200.0, 200.0],
        )
        report = tc._build_comparison(
            results,
            baseline_sha=_BASELINE_SHA,
            head_sha=_HEAD_SHA,
            dependency_match=True,
            common_regression_threshold_pct=10.0,
            head_full_limit_seconds=240.0,
        )
        assert report["all_gates_passed"] is True
        assert report["common_suite"]["gate_passed"] is True
        assert report["head_full_suite"]["gate_passed"] is True
        assert report["head_only_suite"]["gate_passed"] is True

    def test_common_gate_passes_at_5pct_regression(
        self, tc, tmp_path: Path
    ) -> None:
        results = tmp_path / "results"
        _setup_full_comparison(
            results,
            baseline_walls=[100.0, 100.0, 100.0],
            head_walls=[105.0, 105.0, 105.0],
            head_full_walls=[200.0, 200.0, 200.0],
        )
        report = tc._build_comparison(
            results,
            baseline_sha=_BASELINE_SHA,
            head_sha=_HEAD_SHA,
            dependency_match=True,
            common_regression_threshold_pct=10.0,
            head_full_limit_seconds=240.0,
        )
        assert report["common_suite"]["gate_passed"] is True
        assert report["all_gates_passed"] is True

    def test_common_gate_fails_at_15pct_regression(
        self, tc, tmp_path: Path
    ) -> None:
        results = tmp_path / "results"
        _setup_full_comparison(
            results,
            baseline_walls=[100.0, 100.0, 100.0],
            head_walls=[115.0, 115.0, 115.0],
            head_full_walls=[200.0, 200.0, 200.0],
        )
        report = tc._build_comparison(
            results,
            baseline_sha=_BASELINE_SHA,
            head_sha=_HEAD_SHA,
            dependency_match=True,
            common_regression_threshold_pct=10.0,
            head_full_limit_seconds=240.0,
        )
        assert report["common_suite"]["gate_passed"] is False
        assert report["all_gates_passed"] is False

    def test_common_gate_uses_median_of_three_pairs(
        self, tc, tmp_path: Path
    ) -> None:
        """The common gate uses the paired median delta_pct, not the
        average or max.  With deltas of [+5%, +15%, +5%], the median
        is +5% which passes the 10% gate."""
        results = tmp_path / "results"
        _setup_full_comparison(
            results,
            baseline_walls=[100.0, 100.0, 100.0],
            head_walls=[105.0, 115.0, 105.0],
            head_full_walls=[200.0, 200.0, 200.0],
        )
        report = tc._build_comparison(
            results,
            baseline_sha=_BASELINE_SHA,
            head_sha=_HEAD_SHA,
            dependency_match=True,
            common_regression_threshold_pct=10.0,
            head_full_limit_seconds=240.0,
        )
        assert report["common_suite"]["gate_passed"] is True
        assert report["common_suite"]["paired_median_delta_percent"] == 5.0

    def test_full_head_gate_fails_above_240_seconds(
        self, tc, tmp_path: Path
    ) -> None:
        results = tmp_path / "results"
        _setup_full_comparison(
            results,
            baseline_walls=[100.0, 100.0, 100.0],
            head_walls=[100.0, 100.0, 100.0],
            head_full_walls=[250.0, 250.0, 250.0],
        )
        report = tc._build_comparison(
            results,
            baseline_sha=_BASELINE_SHA,
            head_sha=_HEAD_SHA,
            dependency_match=True,
            common_regression_threshold_pct=10.0,
            head_full_limit_seconds=240.0,
        )
        assert report["head_full_suite"]["gate_passed"] is False
        assert report["all_gates_passed"] is False

    def test_full_head_gate_passes_at_240_seconds(
        self, tc, tmp_path: Path
    ) -> None:
        results = tmp_path / "results"
        _setup_full_comparison(
            results,
            baseline_walls=[100.0, 100.0, 100.0],
            head_walls=[100.0, 100.0, 100.0],
            head_full_walls=[240.0, 240.0, 240.0],
        )
        report = tc._build_comparison(
            results,
            baseline_sha=_BASELINE_SHA,
            head_sha=_HEAD_SHA,
            dependency_match=True,
            common_regression_threshold_pct=10.0,
            head_full_limit_seconds=240.0,
        )
        assert report["head_full_suite"]["gate_passed"] is True

    def test_dependency_mismatch_fails_all_gates(
        self, tc, tmp_path: Path
    ) -> None:
        results = tmp_path / "results"
        _setup_full_comparison(
            results,
            baseline_walls=[100.0, 100.0, 100.0],
            head_walls=[100.0, 100.0, 100.0],
            head_full_walls=[200.0, 200.0, 200.0],
            dependency_match="false",
        )
        report = tc._build_comparison(
            results,
            baseline_sha=_BASELINE_SHA,
            head_sha=_HEAD_SHA,
            dependency_match=False,
            common_regression_threshold_pct=10.0,
            head_full_limit_seconds=240.0,
        )
        assert report["dependency_match"] is False
        assert report["all_gates_passed"] is False

    def test_invalid_run_fails_all_gates(
        self, tc, tmp_path: Path
    ) -> None:
        """A run with valid=False fails the all_runs_valid gate."""
        results = tmp_path / "results"
        _setup_full_comparison(
            results,
            baseline_walls=[100.0, 100.0, 100.0],
            head_walls=[100.0, 100.0, 100.0],
            head_full_walls=[200.0, 200.0, 200.0],
        )
        # Overwrite one HEAD-full run-result to be invalid.
        run_path = results / "head-full" / "run-1" / "run-result.json"
        payload = json.loads(run_path.read_text(encoding="utf-8"))
        payload["valid"] = False
        _write_json(run_path, payload)
        report = tc._build_comparison(
            results,
            baseline_sha=_BASELINE_SHA,
            head_sha=_HEAD_SHA,
            dependency_match=True,
            common_regression_threshold_pct=10.0,
            head_full_limit_seconds=240.0,
        )
        assert report["all_runs_valid"] is False
        assert report["all_gates_passed"] is False

    def test_head_only_count_zero_vacuously_passes(
        self, tc, tmp_path: Path
    ) -> None:
        """When head_only_count is 0, the head-only gate is vacuously passed."""
        results = tmp_path / "results"
        _setup_full_comparison(
            results,
            baseline_walls=[100.0, 100.0, 100.0],
            head_walls=[100.0, 100.0, 100.0],
            head_full_walls=[200.0, 200.0, 200.0],
            head_only_count=0,
        )
        report = tc._build_comparison(
            results,
            baseline_sha=_BASELINE_SHA,
            head_sha=_HEAD_SHA,
            dependency_match=True,
            common_regression_threshold_pct=10.0,
            head_full_limit_seconds=240.0,
        )
        assert report["head_only_suite"]["gate_passed"] is True
        assert report["head_only_suite"]["runs"] == []

    def test_head_only_count_nonzero_loads_runs(
        self, tc, tmp_path: Path
    ) -> None:
        results = tmp_path / "results"
        _setup_full_comparison(
            results,
            baseline_walls=[100.0, 100.0, 100.0],
            head_walls=[100.0, 100.0, 100.0],
            head_full_walls=[200.0, 200.0, 200.0],
            head_only_count=2,
            head_only_walls=[5.0, 5.0, 5.0],
        )
        report = tc._build_comparison(
            results,
            baseline_sha=_BASELINE_SHA,
            head_sha=_HEAD_SHA,
            dependency_match=True,
            common_regression_threshold_pct=10.0,
            head_full_limit_seconds=240.0,
        )
        assert len(report["head_only_suite"]["runs"]) == 3
        assert report["head_only_suite"]["gate_passed"] is True


class TestBuildComparisonFailClosed:
    """Tests for fail-closed behavior in _build_comparison."""

    def test_missing_manifest_raises_validation_error(
        self, tc, tmp_path: Path
    ) -> None:
        results = tmp_path / "results"
        results.mkdir(parents=True, exist_ok=True)
        with pytest.raises(tc.ValidationError, match="manifest missing"):
            tc._build_comparison(
                results,
                baseline_sha=_BASELINE_SHA,
                head_sha=_HEAD_SHA,
                dependency_match=True,
                common_regression_threshold_pct=10.0,
                head_full_limit_seconds=240.0,
            )

    def test_manifest_wrong_schema_raises_validation_error(
        self, tc, tmp_path: Path
    ) -> None:
        results = tmp_path / "results"
        sel = results / "selection"
        sel.mkdir(parents=True, exist_ok=True)
        _write_json(sel / "manifest.json", {
            "schema_version": 99,
            "baseline_sha": _BASELINE_SHA,
            "head_sha": _HEAD_SHA,
        })
        with pytest.raises(tc.ValidationError, match="schema_version"):
            tc._build_comparison(
                results,
                baseline_sha=_BASELINE_SHA,
                head_sha=_HEAD_SHA,
                dependency_match=True,
                common_regression_threshold_pct=10.0,
                head_full_limit_seconds=240.0,
            )

    def test_manifest_wrong_baseline_sha_raises_validation_error(
        self, tc, tmp_path: Path
    ) -> None:
        results = tmp_path / "results"
        sel = results / "selection"
        sel.mkdir(parents=True, exist_ok=True)
        _write_json(sel / "manifest.json", {
            "schema_version": 1,
            "baseline_sha": "wrong",
            "head_sha": _HEAD_SHA,
        })
        with pytest.raises(tc.ValidationError, match="baseline_sha"):
            tc._build_comparison(
                results,
                baseline_sha=_BASELINE_SHA,
                head_sha=_HEAD_SHA,
                dependency_match=True,
                common_regression_threshold_pct=10.0,
                head_full_limit_seconds=240.0,
            )

    def test_manifest_wrong_head_sha_raises_validation_error(
        self, tc, tmp_path: Path
    ) -> None:
        results = tmp_path / "results"
        sel = results / "selection"
        sel.mkdir(parents=True, exist_ok=True)
        _write_json(sel / "manifest.json", {
            "schema_version": 1,
            "baseline_sha": _BASELINE_SHA,
            "head_sha": "wrong",
        })
        with pytest.raises(tc.ValidationError, match="head_sha"):
            tc._build_comparison(
                results,
                baseline_sha=_BASELINE_SHA,
                head_sha=_HEAD_SHA,
                dependency_match=True,
                common_regression_threshold_pct=10.0,
                head_full_limit_seconds=240.0,
            )

    def test_missing_pair_timing_raises_validation_error(
        self, tc, tmp_path: Path
    ) -> None:
        results = tmp_path / "results"
        _setup_full_comparison(
            results,
            baseline_walls=[100.0, 100.0, 100.0],
            head_walls=[100.0, 100.0, 100.0],
            head_full_walls=[200.0, 200.0, 200.0],
        )
        # Delete one pair's timing.json.
        (results / "pair-2" / "baseline" / "timing.json").unlink()
        with pytest.raises(tc.ValidationError, match="timing.json missing"):
            tc._build_comparison(
                results,
                baseline_sha=_BASELINE_SHA,
                head_sha=_HEAD_SHA,
                dependency_match=True,
                common_regression_threshold_pct=10.0,
                head_full_limit_seconds=240.0,
            )


# ---------------------------------------------------------------------------
# Compare mode: stable regressions and module attribution
# ---------------------------------------------------------------------------

class TestStableRegressions:
    """Tests for the stable-regression attribution logic."""

    def test_stable_regression_detected_when_head_slower_in_all_pairs(
        self, tc, tmp_path: Path
    ) -> None:
        results = tmp_path / "results"
        common_tests_b = [
            _make_test_entry("tests/test_a.py::test_one", total_seconds=0.1),
        ]
        common_tests_h = [
            _make_test_entry("tests/test_a.py::test_one", total_seconds=0.5),
        ]
        _setup_full_comparison(
            results,
            baseline_walls=[100.0, 100.0, 100.0],
            head_walls=[100.0, 100.0, 100.0],
            head_full_walls=[200.0, 200.0, 200.0],
            common_count=1,
            common_tests=common_tests_b,
        )
        # Overwrite HEAD timing to have slower test_one in all 3 pairs.
        for i in range(3):
            h_timing_path = results / f"pair-{i + 1}" / "head" / "timing.json"
            payload = json.loads(h_timing_path.read_text(encoding="utf-8"))
            payload["tests"] = common_tests_h
            _write_json(h_timing_path, payload)

        report = tc._build_comparison(
            results,
            baseline_sha=_BASELINE_SHA,
            head_sha=_HEAD_SHA,
            dependency_match=True,
            common_regression_threshold_pct=10.0,
            head_full_limit_seconds=240.0,
        )
        stable = report["stable_regressions"]
        assert len(stable) == 1
        assert stable[0]["test"] == "tests/test_a.py::test_one"
        assert stable[0]["baseline_median"] == 0.1
        assert stable[0]["head_median"] == 0.5

    def test_no_stable_regression_when_head_not_consistently_slower(
        self, tc, tmp_path: Path
    ) -> None:
        results = tmp_path / "results"
        b_tests = [
            _make_test_entry("tests/test_a.py::test_one", total_seconds=0.1),
        ]
        # HEAD is slower in pair 1 and 3, but faster in pair 2.
        h_tests = [
            _make_test_entry("tests/test_a.py::test_one", total_seconds=0.5),
        ]
        h_tests_faster = [
            _make_test_entry("tests/test_a.py::test_one", total_seconds=0.05),
        ]
        _setup_full_comparison(
            results,
            baseline_walls=[100.0, 100.0, 100.0],
            head_walls=[100.0, 100.0, 100.0],
            head_full_walls=[200.0, 200.0, 200.0],
            common_count=1,
            common_tests=b_tests,
        )
        for i in range(3):
            h_timing_path = results / f"pair-{i + 1}" / "head" / "timing.json"
            payload = json.loads(h_timing_path.read_text(encoding="utf-8"))
            payload["tests"] = h_tests_faster if i == 1 else h_tests
            _write_json(h_timing_path, payload)

        report = tc._build_comparison(
            results,
            baseline_sha=_BASELINE_SHA,
            head_sha=_HEAD_SHA,
            dependency_match=True,
            common_regression_threshold_pct=10.0,
            head_full_limit_seconds=240.0,
        )
        assert len(report["stable_regressions"]) == 0

    def test_module_attribution_extracts_module_from_nodeid(
        self, tc, tmp_path: Path
    ) -> None:
        results = tmp_path / "results"
        b_tests = [
            _make_test_entry("tests/test_a.py::test_one", total_seconds=0.1),
            _make_test_entry("tests/test_b.py::test_two", total_seconds=0.1),
        ]
        h_tests = [
            _make_test_entry("tests/test_a.py::test_one", total_seconds=0.1),
            _make_test_entry("tests/test_b.py::test_two", total_seconds=0.1),
        ]
        _setup_full_comparison(
            results,
            baseline_walls=[100.0, 100.0, 100.0],
            head_walls=[100.0, 100.0, 100.0],
            head_full_walls=[200.0, 200.0, 200.0],
            common_count=2,
            common_tests=b_tests,
        )
        for i in range(3):
            h_timing_path = results / f"pair-{i + 1}" / "head" / "timing.json"
            payload = json.loads(h_timing_path.read_text(encoding="utf-8"))
            payload["tests"] = h_tests
            _write_json(h_timing_path, payload)

        report = tc._build_comparison(
            results,
            baseline_sha=_BASELINE_SHA,
            head_sha=_HEAD_SHA,
            dependency_match=True,
            common_regression_threshold_pct=10.0,
            head_full_limit_seconds=240.0,
        )
        module_deltas = {m["module"]: m for m in report["common_suite"]["top_module_deltas"]}
        assert "tests/test_a.py" in module_deltas
        assert "tests/test_b.py" in module_deltas
        assert module_deltas["tests/test_a.py"]["count"] == 1


# ---------------------------------------------------------------------------
# Compare mode: exit code semantics via main()
# ---------------------------------------------------------------------------

class TestMainExitCodes:
    """Verify the fail-closed exit codes from main()."""

    def test_main_compare_returns_0_when_all_gates_pass(
        self, tc, tmp_path: Path, monkeypatch
    ) -> None:
        results = tmp_path / "results"
        _setup_full_comparison(
            results,
            baseline_walls=[100.0, 100.0, 100.0],
            head_walls=[100.0, 100.0, 100.0],
            head_full_walls=[200.0, 200.0, 200.0],
        )
        monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
        monkeypatch.setattr(sys, "argv", [
            "timing_comparison.py",
            "--results-dir", str(results),
            "--baseline-sha", _BASELINE_SHA,
            "--head-sha", _HEAD_SHA,
            "--dependency-match", "true",
            "--compare",
        ])
        exit_code = tc.main()
        assert exit_code == 0
        # Verify artifacts written.
        assert (results / "timing-comparison.json").is_file()
        assert (results / "timing-comparison.md").is_file()

    def test_main_compare_returns_4_on_gate_failure(
        self, tc, tmp_path: Path, monkeypatch
    ) -> None:
        results = tmp_path / "results"
        _setup_full_comparison(
            results,
            baseline_walls=[100.0, 100.0, 100.0],
            head_walls=[115.0, 115.0, 115.0],  # 15% regression
            head_full_walls=[200.0, 200.0, 200.0],
        )
        monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
        monkeypatch.setattr(sys, "argv", [
            "timing_comparison.py",
            "--results-dir", str(results),
            "--baseline-sha", _BASELINE_SHA,
            "--head-sha", _HEAD_SHA,
            "--dependency-match", "true",
            "--compare",
        ])
        exit_code = tc.main()
        assert exit_code == tc._EXIT_GATE_FAILED

    def test_main_compare_returns_2_on_missing_manifest(
        self, tc, tmp_path: Path, monkeypatch
    ) -> None:
        results = tmp_path / "results"
        results.mkdir(parents=True, exist_ok=True)
        monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
        monkeypatch.setattr(sys, "argv", [
            "timing_comparison.py",
            "--results-dir", str(results),
            "--baseline-sha", _BASELINE_SHA,
            "--head-sha", _HEAD_SHA,
            "--dependency-match", "true",
            "--compare",
        ])
        exit_code = tc.main()
        assert exit_code == tc._EXIT_INPUT_SCHEMA

    def test_main_compare_returns_3_on_incomplete_run(
        self, tc, tmp_path: Path, monkeypatch
    ) -> None:
        results = tmp_path / "results"
        _setup_full_comparison(
            results,
            baseline_walls=[100.0, 100.0, 100.0],
            head_walls=[100.0, 100.0, 100.0],
            head_full_walls=[200.0, 200.0, 200.0],
        )
        # Inject a failure into one pair's HEAD run-result to make the
        # run incomplete (exit code 3, not 2).  A missing file would be
        # exit 2 (schema/input error); a present-but-failed run is exit 3.
        run_path = results / "pair-2" / "head" / "run-result.json"
        payload = json.loads(run_path.read_text(encoding="utf-8"))
        payload["failure_count"] = 1
        _write_json(run_path, payload)
        monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
        monkeypatch.setattr(sys, "argv", [
            "timing_comparison.py",
            "--results-dir", str(results),
            "--baseline-sha", _BASELINE_SHA,
            "--head-sha", _HEAD_SHA,
            "--dependency-match", "true",
            "--compare",
        ])
        exit_code = tc.main()
        assert exit_code == tc._EXIT_INCOMPLETE

    def test_main_prepare_returns_0_on_success(
        self, tc, tmp_path: Path, monkeypatch
    ) -> None:
        results = tmp_path / "results"
        _build_collection_dir(
            results,
            baseline_ids=["tests/test_a.py::test_one"],
            head_ids=["tests/test_a.py::test_one"],
        )
        monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
        monkeypatch.setattr(sys, "argv", [
            "timing_comparison.py",
            "--results-dir", str(results),
            "--baseline-sha", _BASELINE_SHA,
            "--head-sha", _HEAD_SHA,
            "--dependency-match", "true",
            "--write-selection-only",
        ])
        exit_code = tc.main()
        assert exit_code == 0
        assert (results / "selection" / "manifest.json").is_file()

    def test_main_prepare_returns_2_on_missing_collection(
        self, tc, tmp_path: Path, monkeypatch
    ) -> None:
        results = tmp_path / "results"
        results.mkdir(parents=True, exist_ok=True)
        monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
        monkeypatch.setattr(sys, "argv", [
            "timing_comparison.py",
            "--results-dir", str(results),
            "--baseline-sha", _BASELINE_SHA,
            "--head-sha", _HEAD_SHA,
            "--dependency-match", "true",
            "--write-selection-only",
        ])
        exit_code = tc.main()
        assert exit_code == tc._EXIT_INPUT_SCHEMA


# ---------------------------------------------------------------------------
# Compare mode: missing data does not default to zero
# ---------------------------------------------------------------------------

class TestMissingDataNotZero:
    """Verify that missing data raises rather than silently being treated as 0."""

    def test_missing_timing_json_raises_not_zero(
        self, tc, tmp_path: Path
    ) -> None:
        """A missing timing.json must raise ValidationError, not silently
        produce a 0-second measurement."""
        with pytest.raises(tc.ValidationError):
            tc._load_timing_json(tmp_path / "missing.json")

    def test_missing_run_result_raises_not_zero(
        self, tc, tmp_path: Path
    ) -> None:
        with pytest.raises(tc.ValidationError, match="run-result.json missing"):
            tc._load_run_result(tmp_path / "missing.json")

    def test_zero_wall_clock_raises_not_silent(
        self, tc, tmp_path: Path
    ) -> None:
        """A run with elapsed_seconds=0 must raise IncompleteRunError,
        not be treated as a valid 0-second run."""
        results = tmp_path / "results"
        common_hash = "abc"
        pair_dir = results / "pair-1"
        b_dir = pair_dir / "baseline"
        h_dir = pair_dir / "head"
        _write_json(
            b_dir / "timing.json",
            _make_timing_payload(
                revision=_BASELINE_SHA, selection_hash=common_hash,
                selected_count=1,
            ),
        )
        _write_json(
            h_dir / "timing.json",
            _make_timing_payload(
                revision=_HEAD_SHA, selection_hash=common_hash,
                selected_count=1,
            ),
        )
        _write_json(b_dir / "run-result.json", _make_run_result(elapsed_seconds=0.0))
        _write_json(h_dir / "run-result.json", _make_run_result())
        with pytest.raises(tc.IncompleteRunError):
            tc._load_pair(
                results, 1,
                baseline_sha=_BASELINE_SHA,
                head_sha=_HEAD_SHA,
                common_selection_hash=common_hash,
                common_count=1,
            )
