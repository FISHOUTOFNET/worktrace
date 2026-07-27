"""Unit tests for the HEAD-owned compact-storage memory gate driver.

Covers the pure-Python functions in ``scripts/ci/compact_memory_driver.py``:
schema constants, error category constants, target-root path isolation,
module verification, atomic checkpoint writes via ``ProgressRecorder``,
the relative gate validation in ``_validate_gate``, atomic JSON writes,
runner metadata, argument parsing, and the contract that the gate uses
tracemalloc (NOT RSS), size 5000 (NOT 20000), and a relative median
comparison (NOT a fixed MB threshold).

The driver's full subprocess execution path (which spawns
``tests/support/peak_memory_probe.py`` three times per mode) is NOT
exercised here — that is the responsibility of the GitHub Actions
compact-memory workflow.  These tests cover the driver's deterministic
infrastructure and the pure-Python gate logic, both of which can be
validated without spawning subprocesses.

The script is loaded from its file path because ``scripts/ci/`` is not
a Python package; using ``importlib`` keeps the test hermetic.
"""

from __future__ import annotations

import importlib.util
import inspect
import json
import sys
from pathlib import Path
from typing import Any

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.contract, pytest.mark.parallel_safe]

ROOT = Path(__file__).resolve().parents[1]
DRIVER_PATH = ROOT / "scripts" / "ci" / "compact_memory_driver.py"


# ---------------------------------------------------------------------------
# Module loading fixture
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def driver():
    """Load scripts/ci/compact_memory_driver.py as a module."""
    spec = importlib.util.spec_from_file_location(
        "compact_memory_driver_under_test", DRIVER_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["compact_memory_driver_under_test"] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop("compact_memory_driver_under_test", None)
        raise
    return module


# ---------------------------------------------------------------------------
# Schema constants and exit codes
# ---------------------------------------------------------------------------

class TestSchemaConstants:
    """Verify the driver's schema, version, and gate-sizing constants."""

    def test_driver_version_is_1(self, driver) -> None:
        assert driver._DRIVER_VERSION == "1.0"

    def test_schema_version_is_3(self, driver) -> None:
        assert driver._SCHEMA_VERSION == 3

    def test_default_size_is_5000(self, driver) -> None:
        """The gate is defined at size=5000; do not change without
        updating the contract."""
        assert driver._DEFAULT_SIZE == 5000

    def test_runs_per_mode_is_3(self, driver) -> None:
        """3 compact + 3 expanded subprocesses per gate run."""
        assert driver._RUNS_PER_MODE == 3

    def test_subprocess_timeout_is_120_seconds(self, driver) -> None:
        assert driver._SUBPROCESS_TIMEOUT_SECONDS == 120

    def test_measurement_semantics_is_tracemalloc(self, driver) -> None:
        """tracemalloc is the ONLY memory source — RSS is never used."""
        assert driver._MEASUREMENT_SEMANTICS == "tracemalloc peak bytes"

    def test_exit_codes_are_distinct_and_nonzero(self, driver) -> None:
        assert driver._EXIT_INPUT_SCHEMA == 2
        assert driver._EXIT_EXECUTION == 3
        assert driver._EXIT_INPUT_SCHEMA != driver._EXIT_EXECUTION

    def test_exit_for_category_mapping(self, driver) -> None:
        """Each error category maps to the documented exit code."""
        assert (
            driver._EXIT_FOR_CATEGORY[driver.ERROR_INPUT_SCHEMA]
            == driver._EXIT_INPUT_SCHEMA
        )
        assert (
            driver._EXIT_FOR_CATEGORY[driver.ERROR_REVISION_MISMATCH]
            == driver._EXIT_INPUT_SCHEMA
        )
        for cat in (
            driver.ERROR_COMPACT_RUN,
            driver.ERROR_EXPANDED_RUN,
            driver.ERROR_RESULT_VALIDATION,
            driver.ERROR_INTERRUPTED,
            driver.ERROR_UNEXPECTED,
        ):
            assert driver._EXIT_FOR_CATEGORY[cat] == driver._EXIT_EXECUTION


# ---------------------------------------------------------------------------
# Error category constants
# ---------------------------------------------------------------------------

class TestErrorCategories:
    """Verify the error category constants are defined and distinct."""

    def test_all_error_categories_defined(self, driver) -> None:
        """All 7 error categories must be defined as module constants."""
        assert driver.ERROR_INPUT_SCHEMA == "input_schema_error"
        assert driver.ERROR_REVISION_MISMATCH == "revision_mismatch"
        assert driver.ERROR_COMPACT_RUN == "compact_run_error"
        assert driver.ERROR_EXPANDED_RUN == "expanded_run_error"
        assert driver.ERROR_RESULT_VALIDATION == "result_validation_error"
        assert driver.ERROR_INTERRUPTED == "interrupted"
        assert driver.ERROR_UNEXPECTED == "unexpected_error"

    def test_error_categories_are_distinct(self, driver) -> None:
        """Each error category must be a unique non-empty string."""
        categories = [
            driver.ERROR_INPUT_SCHEMA,
            driver.ERROR_REVISION_MISMATCH,
            driver.ERROR_COMPACT_RUN,
            driver.ERROR_EXPANDED_RUN,
            driver.ERROR_RESULT_VALIDATION,
            driver.ERROR_INTERRUPTED,
            driver.ERROR_UNEXPECTED,
        ]
        assert len(categories) == len(set(categories))
        for cat in categories:
            assert isinstance(cat, str)
            assert len(cat) > 0


# ---------------------------------------------------------------------------
# Contract: NO 20k memory metric, NO RSS, NO fixed MB threshold
# ---------------------------------------------------------------------------

class TestNoLargeScaleMemoryMetric:
    """The compact-memory gate is defined at size=5000 only.

    It must NOT include any 20k projection-memory metric (the 20k
    latency scenarios live in ``product_benchmark_driver.py``).  It must
    NOT use RSS or a fixed MB threshold.
    """

    def test_no_scenarios_dict(self, driver) -> None:
        """The compact-memory driver is single-scenario; it has no
        ``_SCENARIOS`` dict (unlike ``product_benchmark_driver.py``)."""
        assert not hasattr(driver, "_SCENARIOS")

    def test_no_20k_scenarios_or_metric_keys(self, driver) -> None:
        """No 20k projection-memory scenario or metric key is registered
        in any module-level dict.  (The driver docstring explicitly
        documents the absence of 20000; that is fine — what matters is
        that no operational constant references it.)"""
        # No _SCENARIOS dict at all (single-scenario driver).
        assert not hasattr(driver, "_SCENARIOS")
        # No 20k-style metric keys defined as module-level constants.
        metric_attrs = [
            name for name in dir(driver)
            if name.isupper() and "PROJECTION" in name
        ]
        assert metric_attrs == [], (
            f"compact-memory driver must not define projection-metric "
            f"constants; found {metric_attrs}"
        )

    def test_default_size_is_not_20000(self, driver) -> None:
        """The driver's default size is 5000, NOT 20000."""
        assert driver._DEFAULT_SIZE == 5000
        assert driver._DEFAULT_SIZE != 20000

    def test_no_rss_in_measurement_semantics(self, driver) -> None:
        """``_MEASUREMENT_SEMANTICS`` is tracemalloc-only, never RSS."""
        semantics = driver._MEASUREMENT_SEMANTICS
        assert "tracemalloc" in semantics.lower()
        assert "rss" not in semantics.lower()

    def test_gate_validation_uses_no_rss(self, driver) -> None:
        """The gate validation function never references RSS."""
        gate_source = inspect.getsource(driver._validate_gate)
        assert "rss" not in gate_source.lower()
        # The gate uses tracemalloc peak_bytes exclusively.
        assert "peak_bytes" in gate_source

    def test_gate_validation_uses_no_fixed_mb_threshold(self, driver) -> None:
        """The gate validation function uses no fixed MB threshold.

        The gate is RELATIVE only: compact median peak < expanded median
        peak.  Verified behaviorally by passing in arbitrary small
        absolute values — the gate must care only about the relative
        ordering, not about any absolute MB cutoff.
        """
        # Pass tiny absolute values (well under any plausible MB threshold).
        # If the gate used a fixed MB cutoff, this run would always pass/fail
        # regardless of the compact<expanded relationship.  The gate must
        # pass purely because 10 < 20.
        compact_runs = [
            {
                "mode": "compact", "size": 5000, "entry_count": 100,
                "contribution_count": 50,
                "duplicated_contribution_count": 0,
                "current_bytes": 10, "peak_bytes": 10, "run_index": i,
            }
            for i in range(3)
        ]
        expanded_runs = [
            {
                "mode": "expanded", "size": 5000, "entry_count": 100,
                "contribution_count": 50,
                "duplicated_contribution_count": 5,
                "current_bytes": 20, "peak_bytes": 20, "run_index": i,
            }
            for i in range(3)
        ]
        driver._validate_gate(compact_runs, expanded_runs)

        # And the gate must FAIL when compact >= expanded, regardless of
        # how small the absolute values are.
        compact_runs_too_big = [
            {
                "mode": "compact", "size": 5000, "entry_count": 100,
                "contribution_count": 50,
                "duplicated_contribution_count": 0,
                "current_bytes": 100, "peak_bytes": 100, "run_index": i,
            }
            for i in range(3)
        ]
        expanded_runs_tiny = [
            {
                "mode": "expanded", "size": 5000, "entry_count": 100,
                "contribution_count": 50,
                "duplicated_contribution_count": 5,
                "current_bytes": 20, "peak_bytes": 20, "run_index": i,
            }
            for i in range(3)
        ]
        with pytest.raises(RuntimeError, match="not less than"):
            driver._validate_gate(compact_runs_too_big, expanded_runs_tiny)

    def test_gate_validation_function_signature_takes_no_threshold(
        self, driver
    ) -> None:
        """``_validate_gate`` accepts only ``compact_runs`` and
        ``expanded_runs`` — no threshold parameter."""
        sig = inspect.signature(driver._validate_gate)
        params = list(sig.parameters.keys())
        assert params == ["compact_runs", "expanded_runs"]


# ---------------------------------------------------------------------------
# _validate_gate — pure-Python gate logic (no subprocess)
# ---------------------------------------------------------------------------

class TestValidateGate:
    """Tests for the ``_validate_gate`` pure-Python function.

    The gate asserts:
      * every compact run has ``duplicated_contribution_count == 0``
      * every expanded run has ``duplicated_contribution_count > 0``
      * ``compact_median_peak_bytes < expanded_median_peak_bytes``

    No subprocess is invoked here — we pass synthetic run dicts that
    match the probe's output schema.
    """

    @staticmethod
    def _make_run(
        *,
        peak_bytes: int,
        duplicated_count: int,
        run_index: int = 0,
        mode: str = "compact",
    ) -> dict[str, Any]:
        """Build a synthetic run dict matching the probe's output schema."""
        return {
            "mode": mode,
            "size": 5000,
            "entry_count": 100,
            "contribution_count": 50,
            "duplicated_contribution_count": duplicated_count,
            "current_bytes": peak_bytes,
            "peak_bytes": peak_bytes,
            "run_index": run_index,
        }

    def test_passes_when_all_conditions_met(self, driver) -> None:
        """No exception when compact has zero duplicates, expanded has
        duplicates, and compact median < expanded median."""
        compact_runs = [
            self._make_run(peak_bytes=1000, duplicated_count=0, run_index=0),
            self._make_run(peak_bytes=1100, duplicated_count=0, run_index=1),
            self._make_run(peak_bytes=1050, duplicated_count=0, run_index=2),
        ]
        expanded_runs = [
            self._make_run(
                peak_bytes=2000, duplicated_count=5, run_index=0, mode="expanded"
            ),
            self._make_run(
                peak_bytes=2100, duplicated_count=10, run_index=1, mode="expanded"
            ),
            self._make_run(
                peak_bytes=2050, duplicated_count=7, run_index=2, mode="expanded"
            ),
        ]
        # Must not raise.
        driver._validate_gate(compact_runs, expanded_runs)

    def test_fails_when_any_compact_run_has_duplicates(self, driver) -> None:
        """If ANY compact run has duplicated_contribution_count != 0 the
        gate fails — compact storage must never duplicate contributions."""
        compact_runs = [
            self._make_run(peak_bytes=1000, duplicated_count=0, run_index=0),
            self._make_run(peak_bytes=1100, duplicated_count=1, run_index=1),
            self._make_run(peak_bytes=1050, duplicated_count=0, run_index=2),
        ]
        expanded_runs = [
            self._make_run(
                peak_bytes=2000, duplicated_count=5, run_index=0, mode="expanded"
            ),
            self._make_run(
                peak_bytes=2100, duplicated_count=10, run_index=1, mode="expanded"
            ),
            self._make_run(
                peak_bytes=2050, duplicated_count=7, run_index=2, mode="expanded"
            ),
        ]
        with pytest.raises(RuntimeError, match="compact run"):
            driver._validate_gate(compact_runs, expanded_runs)

    def test_fails_when_any_expanded_run_has_no_duplicates(self, driver) -> None:
        """If ANY expanded run has duplicated_contribution_count <= 0 the
        gate fails — expanded storage must always duplicate."""
        compact_runs = [
            self._make_run(peak_bytes=1000, duplicated_count=0, run_index=0),
            self._make_run(peak_bytes=1100, duplicated_count=0, run_index=1),
            self._make_run(peak_bytes=1050, duplicated_count=0, run_index=2),
        ]
        expanded_runs = [
            self._make_run(
                peak_bytes=2000, duplicated_count=5, run_index=0, mode="expanded"
            ),
            self._make_run(
                peak_bytes=2100, duplicated_count=0, run_index=1, mode="expanded"
            ),
            self._make_run(
                peak_bytes=2050, duplicated_count=7, run_index=2, mode="expanded"
            ),
        ]
        with pytest.raises(RuntimeError, match="expanded run"):
            driver._validate_gate(compact_runs, expanded_runs)

    def test_fails_when_compact_median_not_below_expanded_median(
        self, driver
    ) -> None:
        """Gate fails when compact_median_peak_bytes >= expanded_median_peak_bytes."""
        compact_runs = [
            self._make_run(peak_bytes=3000, duplicated_count=0, run_index=0),
            self._make_run(peak_bytes=3000, duplicated_count=0, run_index=1),
            self._make_run(peak_bytes=3000, duplicated_count=0, run_index=2),
        ]
        expanded_runs = [
            self._make_run(
                peak_bytes=2000, duplicated_count=5, run_index=0, mode="expanded"
            ),
            self._make_run(
                peak_bytes=2000, duplicated_count=10, run_index=1, mode="expanded"
            ),
            self._make_run(
                peak_bytes=2000, duplicated_count=7, run_index=2, mode="expanded"
            ),
        ]
        with pytest.raises(RuntimeError, match="not less than"):
            driver._validate_gate(compact_runs, expanded_runs)

    def test_fails_when_medians_are_equal(self, driver) -> None:
        """Gate fails when compact_median == expanded_median (the
        comparison is strictly less-than)."""
        compact_runs = [
            self._make_run(peak_bytes=2000, duplicated_count=0, run_index=0),
            self._make_run(peak_bytes=2000, duplicated_count=0, run_index=1),
            self._make_run(peak_bytes=2000, duplicated_count=0, run_index=2),
        ]
        expanded_runs = [
            self._make_run(
                peak_bytes=2000, duplicated_count=5, run_index=0, mode="expanded"
            ),
            self._make_run(
                peak_bytes=2000, duplicated_count=10, run_index=1, mode="expanded"
            ),
            self._make_run(
                peak_bytes=2000, duplicated_count=7, run_index=2, mode="expanded"
            ),
        ]
        with pytest.raises(RuntimeError, match="not less than"):
            driver._validate_gate(compact_runs, expanded_runs)

    def test_gate_uses_median_not_mean(self, driver) -> None:
        """The gate compares MEDIANS, not means.

        Construct runs where the mean compact peak > mean expanded peak
        but the median compact peak < median expanded peak.  The gate
        must pass — only the median matters.
        """
        # compact peaks: 1000, 1000, 10000  -> median 1000, mean 4000
        compact_runs = [
            self._make_run(peak_bytes=1000, duplicated_count=0, run_index=0),
            self._make_run(peak_bytes=1000, duplicated_count=0, run_index=1),
            self._make_run(peak_bytes=10000, duplicated_count=0, run_index=2),
        ]
        # expanded peaks: 2000, 2000, 2000  -> median 2000, mean 2000
        expanded_runs = [
            self._make_run(
                peak_bytes=2000, duplicated_count=5, run_index=0, mode="expanded"
            ),
            self._make_run(
                peak_bytes=2000, duplicated_count=10, run_index=1, mode="expanded"
            ),
            self._make_run(
                peak_bytes=2000, duplicated_count=7, run_index=2, mode="expanded"
            ),
        ]
        # Median comparison: 1000 < 2000 — passes despite mean compact > mean expanded.
        driver._validate_gate(compact_runs, expanded_runs)

    def test_gate_checks_every_compact_run(self, driver) -> None:
        """A duplicate in the LAST compact run must still fail the gate."""
        compact_runs = [
            self._make_run(peak_bytes=1000, duplicated_count=0, run_index=0),
            self._make_run(peak_bytes=1100, duplicated_count=0, run_index=1),
            self._make_run(peak_bytes=1050, duplicated_count=2, run_index=2),
        ]
        expanded_runs = [
            self._make_run(
                peak_bytes=2000, duplicated_count=5, run_index=0, mode="expanded"
            ),
            self._make_run(
                peak_bytes=2100, duplicated_count=10, run_index=1, mode="expanded"
            ),
            self._make_run(
                peak_bytes=2050, duplicated_count=7, run_index=2, mode="expanded"
            ),
        ]
        with pytest.raises(RuntimeError, match="compact run"):
            driver._validate_gate(compact_runs, expanded_runs)

    def test_gate_checks_every_expanded_run(self, driver) -> None:
        """A zero-duplicate in the LAST expanded run must still fail."""
        compact_runs = [
            self._make_run(peak_bytes=1000, duplicated_count=0, run_index=0),
            self._make_run(peak_bytes=1100, duplicated_count=0, run_index=1),
            self._make_run(peak_bytes=1050, duplicated_count=0, run_index=2),
        ]
        expanded_runs = [
            self._make_run(
                peak_bytes=2000, duplicated_count=5, run_index=0, mode="expanded"
            ),
            self._make_run(
                peak_bytes=2100, duplicated_count=10, run_index=1, mode="expanded"
            ),
            self._make_run(
                peak_bytes=2050, duplicated_count=0, run_index=2, mode="expanded"
            ),
        ]
        with pytest.raises(RuntimeError, match="expanded run"):
            driver._validate_gate(compact_runs, expanded_runs)


# ---------------------------------------------------------------------------
# ProgressRecorder (atomic checkpoint writer)
# ---------------------------------------------------------------------------

class TestProgressRecorder:
    """Tests for the compact-memory ``ProgressRecorder``."""

    @staticmethod
    def _make_recorder(driver, output_dir: Path, **overrides):
        kwargs = {
            "output_dir": output_dir,
            "requested_revision": "abc123",
            "actual_target_revision": "abc123",
            "schema_version": driver._SCHEMA_VERSION,
            "driver_version": driver._DRIVER_VERSION,
            "size": driver._DEFAULT_SIZE,
            "runner_metadata": {"execution_environment": "local"},
        }
        kwargs.update(overrides)
        return driver.ProgressRecorder(**kwargs)

    def test_initial_state_is_initialized(
        self, driver, tmp_path: Path
    ) -> None:
        recorder = self._make_recorder(driver, tmp_path)
        snapshot = recorder.snapshot()
        assert snapshot["phase"] == "initialized"
        assert snapshot["schema_version"] == driver._SCHEMA_VERSION
        assert snapshot["driver_version"] == driver._DRIVER_VERSION
        assert snapshot["size"] == driver._DEFAULT_SIZE
        assert snapshot["requested_revision"] == "abc123"
        assert snapshot["actual_target_revision"] == "abc123"
        assert snapshot["runner_metadata"] == {"execution_environment": "local"}
        assert snapshot["current_mode"] is None
        assert snapshot["current_run_index"] == -1
        assert snapshot["completed_compact_runs"] == 0
        assert snapshot["completed_expanded_runs"] == 0
        assert snapshot["last_run_summary"] is None

    def test_checkpoint_advances_phase(self, driver, tmp_path: Path) -> None:
        recorder = self._make_recorder(driver, tmp_path)
        recorder.checkpoint("revision_verified")
        assert recorder.snapshot()["phase"] == "revision_verified"

    def test_checkpoint_persists_progress_json(
        self, driver, tmp_path: Path
    ) -> None:
        recorder = self._make_recorder(driver, tmp_path)
        recorder.checkpoint("revision_verified")
        progress_path = tmp_path / "progress.json"
        assert progress_path.is_file()
        loaded = json.loads(progress_path.read_text(encoding="utf-8"))
        assert loaded["phase"] == "revision_verified"
        assert loaded["schema_version"] == driver._SCHEMA_VERSION
        assert loaded["size"] == driver._DEFAULT_SIZE

    def test_checkpoint_updates_compact_counters(
        self, driver, tmp_path: Path
    ) -> None:
        recorder = self._make_recorder(driver, tmp_path)
        recorder.checkpoint(
            "compact_run_completed",
            current_mode="compact",
            current_run_index=0,
            completed_compact_runs=1,
            last_run_summary={
                "run_index": 0,
                "peak_bytes": 1000,
                "duplicated_contribution_count": 0,
            },
        )
        snapshot = recorder.snapshot()
        assert snapshot["current_mode"] == "compact"
        assert snapshot["current_run_index"] == 0
        assert snapshot["completed_compact_runs"] == 1
        assert snapshot["last_run_summary"]["peak_bytes"] == 1000

    def test_checkpoint_updates_expanded_counters(
        self, driver, tmp_path: Path
    ) -> None:
        recorder = self._make_recorder(driver, tmp_path)
        recorder.checkpoint(
            "expanded_run_completed",
            current_mode="expanded",
            current_run_index=2,
            completed_expanded_runs=3,
            last_run_summary={
                "run_index": 2,
                "peak_bytes": 5000,
                "duplicated_contribution_count": 7,
            },
        )
        snapshot = recorder.snapshot()
        assert snapshot["current_mode"] == "expanded"
        assert snapshot["current_run_index"] == 2
        assert snapshot["completed_expanded_runs"] == 3

    def test_checkpoint_writes_atomically(self, driver, tmp_path: Path) -> None:
        """No .tmp file left after a checkpoint."""
        recorder = self._make_recorder(driver, tmp_path)
        recorder.checkpoint("revision_verified")
        tmp_files = list(tmp_path.glob("*.tmp"))
        assert len(tmp_files) == 0

    def test_mark_failed_advances_to_failed_phase(
        self, driver, tmp_path: Path
    ) -> None:
        recorder = self._make_recorder(driver, tmp_path)
        recorder.checkpoint("compact_started")
        recorder.mark_failed(
            failure_category=driver.ERROR_COMPACT_RUN,
            failure_message="compact run 0 failed",
            failure_traceback="trace",
        )
        snapshot = recorder.snapshot()
        assert snapshot["phase"] == "failed"
        assert snapshot["failure_category"] == driver.ERROR_COMPACT_RUN
        assert snapshot["failure_message"] == "compact run 0 failed"
        assert snapshot["failure_traceback"] == "trace"

    def test_mark_failed_persists_failure_metadata(
        self, driver, tmp_path: Path
    ) -> None:
        recorder = self._make_recorder(driver, tmp_path)
        recorder.checkpoint("compact_started")
        recorder.mark_failed(
            failure_category=driver.ERROR_EXPANDED_RUN,
            failure_message="expanded run 1 failed",
        )
        progress_path = tmp_path / "progress.json"
        loaded = json.loads(progress_path.read_text(encoding="utf-8"))
        assert loaded["phase"] == "failed"
        assert loaded["failure_category"] == driver.ERROR_EXPANDED_RUN
        assert loaded["failure_message"] == "expanded run 1 failed"
        # failure_traceback was not set, so it must be absent.
        assert "failure_traceback" not in loaded

    def test_snapshot_returns_copy(self, driver, tmp_path: Path) -> None:
        """snapshot() returns a copy; mutating it doesn't affect the
        recorder's internal state."""
        recorder = self._make_recorder(driver, tmp_path)
        recorder.checkpoint("revision_verified")
        snapshot = recorder.snapshot()
        snapshot["phase"] = "tampered"
        assert recorder.snapshot()["phase"] == "revision_verified"

    def test_phase_elapsed_seconds_resets_per_phase(
        self, driver, tmp_path: Path, monkeypatch
    ) -> None:
        """Each checkpoint resets phase_started_at so phase_elapsed_seconds
        measures only the current phase."""
        current = [1000.0]

        def fake_time() -> float:
            current[0] += 0.05
            return current[0]

        monkeypatch.setattr(driver.time, "time", fake_time)

        recorder = self._make_recorder(driver, tmp_path)
        recorder.checkpoint("revision_verified")
        recorder.checkpoint("compact_started")
        snapshot = recorder.snapshot()
        assert snapshot["phase_elapsed_seconds"] >= 0.0
        assert snapshot["total_elapsed_seconds"] >= snapshot["phase_elapsed_seconds"]


# ---------------------------------------------------------------------------
# Target-root isolation
# ---------------------------------------------------------------------------

class TestSetupTargetPath:
    """Tests for the target-root sys.path isolation."""

    def test_target_root_prepended_to_sys_path(
        self, driver, tmp_path: Path
    ) -> None:
        original_path = list(sys.path)
        try:
            driver._setup_target_path(tmp_path)
            assert sys.path[0] == str(tmp_path)
        finally:
            sys.path = original_path

    def test_existing_target_entry_not_duplicated(
        self, driver, tmp_path: Path
    ) -> None:
        """If target_root is already in sys.path, it is moved to front
        without creating a duplicate."""
        original_path = list(sys.path)
        try:
            sys.path.insert(5, str(tmp_path))
            driver._setup_target_path(tmp_path)
            assert sys.path[0] == str(tmp_path)
            count = sys.path.count(str(tmp_path))
            assert count == 1
        finally:
            sys.path = original_path

    def test_other_entries_preserved(self, driver, tmp_path: Path) -> None:
        """Entries that are not the target root must be preserved."""
        original_path = list(sys.path)
        try:
            driver._setup_target_path(tmp_path)
            for entry in original_path:
                if entry == str(tmp_path):
                    continue
                assert entry in sys.path
        finally:
            sys.path = original_path


class TestVerifyModuleAtTarget:
    """Tests for the module location verification."""

    def test_module_at_target_returns_resolved_path(
        self, driver, tmp_path: Path
    ) -> None:
        """A module whose __file__ is under target_root passes verification."""
        pkg_dir = tmp_path / "fake_pkg"
        pkg_dir.mkdir()
        (pkg_dir / "__init__.py").write_text("", encoding="utf-8")
        original_path = list(sys.path)
        try:
            sys.path.insert(0, str(tmp_path))
            resolved = driver._verify_module_at_target("fake_pkg", tmp_path)
            assert "fake_pkg" in resolved
            assert tmp_path.name in resolved
        finally:
            sys.path = original_path
            sys.modules.pop("fake_pkg", None)

    def test_module_not_at_target_raises_system_exit_2(
        self, driver, tmp_path: Path
    ) -> None:
        """A module whose __file__ is NOT under target_root raises
        SystemExit with exit code 2 (input/schema error)."""
        with pytest.raises(SystemExit) as exc_info:
            driver._verify_module_at_target("json", tmp_path)
        assert exc_info.value.code == driver._EXIT_INPUT_SCHEMA

    def test_nonexistent_module_raises_system_exit_2(
        self, driver, tmp_path: Path
    ) -> None:
        """A module that cannot be imported raises SystemExit(2)."""
        with pytest.raises(SystemExit) as exc_info:
            driver._verify_module_at_target(
                "nonexistent_module_xyz_12345", tmp_path
            )
        assert exc_info.value.code == driver._EXIT_INPUT_SCHEMA


# ---------------------------------------------------------------------------
# _atomic_write_json
# ---------------------------------------------------------------------------

class TestAtomicWriteJson:
    """Tests for the atomic JSON write helper."""

    def test_creates_parent_directories(
        self, driver, tmp_path: Path
    ) -> None:
        output = tmp_path / "deeply" / "nested" / "dir" / "result.json"
        driver._atomic_write_json(output, {"key": "value"})
        assert output.is_file()

    def test_writes_valid_json(self, driver, tmp_path: Path) -> None:
        output = tmp_path / "result.json"
        payload = {"schema_version": 3, "metrics": {"a": [1, 2, 3]}}
        driver._atomic_write_json(output, payload)
        loaded = json.loads(output.read_text(encoding="utf-8"))
        assert loaded == payload

    def test_overwrites_existing_file(self, driver, tmp_path: Path) -> None:
        output = tmp_path / "result.json"
        output.write_text('{"old": true}', encoding="utf-8")
        driver._atomic_write_json(output, {"new": True})
        loaded = json.loads(output.read_text(encoding="utf-8"))
        assert loaded == {"new": True}

    def test_no_tmp_file_left_behind(self, driver, tmp_path: Path) -> None:
        """The atomic write must not leave a .tmp file behind."""
        output = tmp_path / "result.json"
        driver._atomic_write_json(output, {"key": "value"})
        tmp_files = list(tmp_path.glob("*.tmp"))
        assert len(tmp_files) == 0


# ---------------------------------------------------------------------------
# _runner_metadata
# ---------------------------------------------------------------------------

class TestRunnerMetadata:
    """Tests for the runner metadata helper."""

    def test_local_environment_when_not_on_github(
        self, driver, monkeypatch
    ) -> None:
        monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
        meta = driver._runner_metadata()
        assert meta["execution_environment"] == "local"

    def test_github_environment_captures_ci_metadata(
        self, driver, monkeypatch
    ) -> None:
        monkeypatch.setenv("GITHUB_ACTIONS", "true")
        monkeypatch.setenv("GITHUB_SHA", "abc123")
        monkeypatch.setenv("GITHUB_RUN_ID", "98765")
        monkeypatch.setenv("RUNNER_OS", "Windows")
        monkeypatch.setenv("RUNNER_ARCH", "X64")
        meta = driver._runner_metadata()
        assert meta["execution_environment"] == "github_actions"
        assert meta["github_sha"] == "abc123"
        assert meta["github_run_id"] == "98765"
        assert meta["runner_os"] == "Windows"
        assert meta["runner_arch"] == "X64"

    def test_github_environment_with_missing_optional_fields(
        self, driver, monkeypatch
    ) -> None:
        """On GitHub Actions but with some optional env vars unset,
        those fields must be None (not raise)."""
        monkeypatch.setenv("GITHUB_ACTIONS", "true")
        monkeypatch.delenv("GITHUB_SHA", raising=False)
        monkeypatch.delenv("GITHUB_RUN_ID", raising=False)
        monkeypatch.delenv("ImageOS", raising=False)
        meta = driver._runner_metadata()
        assert meta["execution_environment"] == "github_actions"
        assert meta["github_sha"] is None
        assert meta["github_run_id"] is None
        assert meta["runner_image"] is None


# ---------------------------------------------------------------------------
# main() — argument validation
# ---------------------------------------------------------------------------

class TestMainArguments:
    """Tests for main()'s argument parsing via sys.argv.

    The parser is built inline in ``main()``, so these tests invoke
    ``main()`` with various argv and check the exit code.  When the
    target root is invalid, main() exits before running any subprocess,
    so these tests are hermetic.
    """

    def test_missing_target_root_raises_system_exit(
        self, driver, tmp_path: Path, monkeypatch
    ) -> None:
        """Missing --target-root must cause argparse to exit."""
        monkeypatch.setattr(sys, "argv", [
            "compact_memory_driver.py",
            "--revision", "abc123",
            "--output-dir", str(tmp_path / "out"),
        ])
        with pytest.raises(SystemExit):
            driver.main()

    def test_missing_revision_raises_system_exit(
        self, driver, tmp_path: Path, monkeypatch
    ) -> None:
        """Missing --revision must cause argparse to exit."""
        monkeypatch.setattr(sys, "argv", [
            "compact_memory_driver.py",
            "--target-root", str(tmp_path),
            "--output-dir", str(tmp_path / "out"),
        ])
        with pytest.raises(SystemExit):
            driver.main()

    def test_missing_output_dir_raises_system_exit(
        self, driver, tmp_path: Path, monkeypatch
    ) -> None:
        """Missing --output-dir must cause argparse to exit."""
        monkeypatch.setattr(sys, "argv", [
            "compact_memory_driver.py",
            "--target-root", str(tmp_path),
            "--revision", "abc123",
        ])
        with pytest.raises(SystemExit):
            driver.main()


# ---------------------------------------------------------------------------
# main() — target root validation
# ---------------------------------------------------------------------------

class TestMainTargetRootValidation:
    """Tests for main()'s target-root validation (exit code 2)."""

    def test_main_returns_2_when_target_root_does_not_exist(
        self, driver, tmp_path: Path, monkeypatch
    ) -> None:
        nonexistent = tmp_path / "does-not-exist"
        monkeypatch.setattr(sys, "argv", [
            "compact_memory_driver.py",
            "--target-root", str(nonexistent),
            "--revision", "abc123",
            "--output-dir", str(tmp_path / "out"),
        ])
        exit_code = driver.main()
        assert exit_code == driver._EXIT_INPUT_SCHEMA

    def test_main_returns_2_when_target_root_is_file_not_dir(
        self, driver, tmp_path: Path, monkeypatch
    ) -> None:
        file_path = tmp_path / "not-a-dir.txt"
        file_path.write_text("hello", encoding="utf-8")
        monkeypatch.setattr(sys, "argv", [
            "compact_memory_driver.py",
            "--target-root", str(file_path),
            "--revision", "abc123",
            "--output-dir", str(tmp_path / "out"),
        ])
        exit_code = driver.main()
        assert exit_code == driver._EXIT_INPUT_SCHEMA


# ---------------------------------------------------------------------------
# main() — --size argument and default routing
# ---------------------------------------------------------------------------

class TestSizeArgument:
    """Tests for the ``--size`` argument and the ``_run`` routing."""

    def test_default_size_is_5000(self, driver, tmp_path: Path, monkeypatch) -> None:
        """The default --size must be 5000 (the contract size)."""
        captured: dict[str, object] = {}

        def stub_run(**kwargs):
            captured.update(kwargs)
            return 0

        monkeypatch.setattr(driver, "_run", stub_run)
        monkeypatch.setattr(sys, "argv", [
            "compact_memory_driver.py",
            "--target-root", str(tmp_path),
            "--revision", "abc123",
            "--output-dir", str(tmp_path / "out"),
        ])
        exit_code = driver.main()
        assert exit_code == 0
        assert captured["size"] == 5000

    def test_size_override_propagated_to_run(
        self, driver, tmp_path: Path, monkeypatch
    ) -> None:
        """An explicit --size value is propagated to _run."""
        captured: dict[str, object] = {}

        def stub_run(**kwargs):
            captured.update(kwargs)
            return 0

        monkeypatch.setattr(driver, "_run", stub_run)
        monkeypatch.setattr(sys, "argv", [
            "compact_memory_driver.py",
            "--target-root", str(tmp_path),
            "--revision", "abc123",
            "--output-dir", str(tmp_path / "out"),
            "--size", "100",
        ])
        exit_code = driver.main()
        assert exit_code == 0
        assert captured["size"] == 100

    def test_run_function_exists(self, driver) -> None:
        """The ``_run`` function is the main execution entry — it must
        exist and be callable."""
        assert hasattr(driver, "_run")
        assert callable(driver._run)

    def test_run_probe_function_exists(self, driver) -> None:
        """``_run_probe`` exists for subprocess invocation.  Not invoked
        in tests (we test the pure-Python gate logic separately)."""
        assert hasattr(driver, "_run_probe")
        assert callable(driver._run_probe)
