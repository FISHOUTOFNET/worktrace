"""Unit tests for the HEAD-owned product benchmark driver.

Covers the pure-Python functions in ``scripts/ci/product_benchmark_driver.py``:
target-root path isolation, module verification, atomic checkpoint writes via
``ProgressRecorder``, error category constants, scenario registry, time
formatting, atomic JSON writes, runner metadata, argument parsing, and
single-scenario vs local-wrapper routing.

The driver's full benchmark execution path (which imports ``worktrace.*``
and builds a real database) is NOT exercised here — that is the
responsibility of the GitHub Actions performance-validation workflow
and the baseline/HEAD smoke tests.  These tests cover the driver's
deterministic infrastructure that can be validated without a full
worktree.

The script is loaded from its file path because ``scripts/ci/`` is not
a Python package; using ``importlib`` keeps the test hermetic.
"""

from __future__ import annotations

import importlib.util
import inspect
import json
import sys
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.contract, pytest.mark.parallel_safe]

ROOT = Path(__file__).resolve().parents[1]
DRIVER_PATH = ROOT / "scripts" / "ci" / "product_benchmark_driver.py"


# ---------------------------------------------------------------------------
# Module loading fixture
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def driver():
    """Load scripts/ci/product_benchmark_driver.py as a module."""
    spec = importlib.util.spec_from_file_location(
        "product_benchmark_driver_under_test", DRIVER_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["product_benchmark_driver_under_test"] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop("product_benchmark_driver_under_test", None)
        raise
    return module


# ---------------------------------------------------------------------------
# Schema constants and exit codes
# ---------------------------------------------------------------------------

class TestSchemaConstants:
    """Verify the driver's schema and exit-code constants are stable."""

    def test_schema_version_is_3(self, driver) -> None:
        # Schema v3 splits the compact-storage memory gate into its own
        # driver (compact_memory_driver.py) so product_benchmark_driver
        # only owns the two cross-revision latency scenarios.
        assert driver._SCHEMA_VERSION == 3

    def test_driver_version_is_3(self, driver) -> None:
        assert driver._DRIVER_VERSION == "3.0"

    def test_driver_version_is_string(self, driver) -> None:
        assert isinstance(driver._DRIVER_VERSION, str)
        assert len(driver._DRIVER_VERSION) > 0

    def test_exit_codes_are_distinct_and_nonzero(self, driver) -> None:
        assert driver._EXIT_INPUT_SCHEMA == 2
        assert driver._EXIT_EXECUTION == 3
        assert driver._EXIT_INPUT_SCHEMA != driver._EXIT_EXECUTION

    def test_profiles_define_smoke_and_full(self, driver) -> None:
        """The driver must define smoke and full profiles with the
        canonical data sizes for each."""
        assert "smoke" in driver._PROFILES
        assert "full" in driver._PROFILES
        # Smoke uses small data sizes for infrastructure validation.
        assert driver._PROFILES["smoke"]["activity_count"] == 200
        assert driver._PROFILES["smoke"]["contribution_count"] == 200
        assert driver._PROFILES["smoke"]["runs"] == 1
        assert driver._PROFILES["smoke"]["warmup_runs"] == 0
        # Full uses the real performance-gate data sizes.
        assert driver._PROFILES["full"]["activity_count"] == 20000
        assert driver._PROFILES["full"]["contribution_count"] == 10000
        assert driver._PROFILES["full"]["runs"] == 3
        assert driver._PROFILES["full"]["warmup_runs"] == 1

    def test_fixture_parameters_are_fixed_in_shared_module(self, driver) -> None:
        """The fixture parameters now live in the shared benchmark_fixture
        module so product and WebView drivers use the exact same constants."""
        from scripts.ci.benchmark_fixture import (
            DEFAULT_DAY_START_SECONDS,
            DEFAULT_REPORT_DATE,
            DEFAULT_SPAN_SECONDS,
        )
        assert DEFAULT_REPORT_DATE == "2026-07-15"
        assert DEFAULT_DAY_START_SECONDS == 9 * 3600
        assert DEFAULT_SPAN_SECONDS == 13 * 3600


# ---------------------------------------------------------------------------
# Error category constants
# ---------------------------------------------------------------------------

class TestErrorCategories:
    """Verify the error category constants are defined and distinct."""

    def test_all_error_categories_defined(self, driver) -> None:
        """All 10 error categories must be defined as module constants."""
        assert driver.ERROR_INPUT_SCHEMA == "input_schema_error"
        assert driver.ERROR_REVISION_MISMATCH == "revision_mismatch"
        assert driver.ERROR_DATABASE_INIT == "database_init_error"
        assert driver.ERROR_FIXTURE == "fixture_error"
        assert driver.ERROR_FIXTURE_VALIDATION == "fixture_validation_error"
        assert driver.ERROR_WARMUP == "warmup_error"
        assert driver.ERROR_SAMPLE == "sample_error"
        assert driver.ERROR_RESULT_VALIDATION == "result_validation_error"
        assert driver.ERROR_INTERRUPTED == "interrupted"
        assert driver.ERROR_UNEXPECTED == "unexpected_error"

    def test_error_categories_are_distinct(self, driver) -> None:
        """Each error category must be a unique non-empty string."""
        categories = [
            driver.ERROR_INPUT_SCHEMA,
            driver.ERROR_REVISION_MISMATCH,
            driver.ERROR_DATABASE_INIT,
            driver.ERROR_FIXTURE,
            driver.ERROR_FIXTURE_VALIDATION,
            driver.ERROR_WARMUP,
            driver.ERROR_SAMPLE,
            driver.ERROR_RESULT_VALIDATION,
            driver.ERROR_INTERRUPTED,
            driver.ERROR_UNEXPECTED,
        ]
        assert len(categories) == len(set(categories))
        for cat in categories:
            assert isinstance(cat, str)
            assert len(cat) > 0


# ---------------------------------------------------------------------------
# Scenario registry
# ---------------------------------------------------------------------------

class TestScenarios:
    """Tests for the ``_SCENARIOS`` dict — only cross-revision latency
    scenarios live here.  The compact-storage memory gate has its own
    driver (``compact_memory_driver.py``) and must NOT appear in this
    driver's scenarios.
    """

    def test_scenarios_dict_has_exactly_two_entries(self, driver) -> None:
        assert len(driver._SCENARIOS) == 2

    def test_scenarios_include_20k_activities(self, driver) -> None:
        assert "20k_activities" in driver._SCENARIOS
        assert (
            driver._SCENARIOS["20k_activities"]
            == "projection_20k_total_seconds"
        )

    def test_scenarios_include_10k_contributions(self, driver) -> None:
        assert "10k_contributions" in driver._SCENARIOS
        assert (
            driver._SCENARIOS["10k_contributions"]
            == "projection_10k_contributions_seconds"
        )

    def test_no_peak_memory_scenario_in_product_driver(self, driver) -> None:
        """The product driver must NOT include any peak_memory scenario —
        memory measurement lives in ``compact_memory_driver.py``."""
        for scenario_key, metric_key in driver._SCENARIOS.items():
            assert "peak_memory" not in scenario_key
            assert "memory" not in metric_key.lower()
        assert "peak_memory" not in driver._SCENARIOS
        assert "compact_memory" not in driver._SCENARIOS


# ---------------------------------------------------------------------------
# Target-root isolation
# ---------------------------------------------------------------------------

class TestSetupTargetPath:
    """Tests for the target-root sys.path isolation."""

    def test_target_root_prepended_to_sys_path(self, driver, tmp_path: Path) -> None:
        original_path = list(sys.path)
        try:
            driver._setup_target_path(tmp_path)
            assert sys.path[0] == str(tmp_path)
        finally:
            sys.path = original_path

    def test_existing_target_entry_not_duplicated(self, driver, tmp_path: Path) -> None:
        """If target_root is already in sys.path, it is moved to front
        without creating a duplicate."""
        original_path = list(sys.path)
        try:
            sys.path.insert(5, str(tmp_path))
            driver._setup_target_path(tmp_path)
            assert sys.path[0] == str(tmp_path)
            # Should appear exactly once.
            count = sys.path.count(str(tmp_path))
            assert count == 1
        finally:
            sys.path = original_path

    def test_other_entries_preserved(self, driver, tmp_path: Path) -> None:
        """Entries that are not the target root must be preserved."""
        original_path = list(sys.path)
        try:
            driver._setup_target_path(tmp_path)
            # All original entries (except target_root if it was already
            # present) should still be in sys.path, just shifted down.
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
        # Create a synthetic module file under tmp_path.
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
        # 'json' is a stdlib module, definitely not under tmp_path.
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
# ProgressRecorder (atomic checkpoint writer)
# ---------------------------------------------------------------------------

class TestProgressRecorder:
    """Tests for the ``ProgressRecorder`` atomic checkpoint writer."""

    @staticmethod
    def _make_recorder(driver, output_dir: Path, **overrides):
        kwargs = {
            "output_dir": output_dir,
            "scenario": "20k_activities",
            "profile": "full",
            "requested_revision": "abc123",
            "actual_target_revision": "abc123",
            "schema_version": driver._SCHEMA_VERSION,
            "driver_version": driver._DRIVER_VERSION,
            "runner_metadata": {"execution_environment": "local"},
        }
        kwargs.update(overrides)
        return driver.ProgressRecorder(**kwargs)

    def test_initial_state_is_initialized(self, driver, tmp_path: Path) -> None:
        recorder = self._make_recorder(driver, tmp_path)
        snapshot = recorder.snapshot()
        assert snapshot["phase"] == "initialized"
        assert snapshot["schema_version"] == driver._SCHEMA_VERSION
        assert snapshot["driver_version"] == driver._DRIVER_VERSION
        assert snapshot["scenario"] == "20k_activities"
        assert snapshot["profile"] == "full"
        assert snapshot["requested_revision"] == "abc123"
        assert snapshot["actual_target_revision"] == "abc123"
        assert snapshot["runner_metadata"] == {"execution_environment": "local"}

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

    def test_checkpoint_updates_counters(self, driver, tmp_path: Path) -> None:
        recorder = self._make_recorder(driver, tmp_path)
        recorder.checkpoint(
            "fixture_completed",
            inserted_count=20000,
            requested_count=20000,
            chunk_index=39,
            completed_samples=0,
            current_sample_index=-1,
        )
        snapshot = recorder.snapshot()
        assert snapshot["inserted_count"] == 20000
        assert snapshot["requested_count"] == 20000
        assert snapshot["chunk_index"] == 39
        assert snapshot["completed_samples"] == 0

    def test_checkpoint_persists_fixture_audit(
        self, driver, tmp_path: Path
    ) -> None:
        recorder = self._make_recorder(driver, tmp_path)
        audit = {"scenario": "20k_activities", "inserted_count": 20000}
        recorder.checkpoint("fixture_completed", fixture_audit=audit)
        snapshot = recorder.snapshot()
        assert snapshot["fixture_audit"] == audit

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
        recorder.checkpoint("revision_verified")
        recorder.mark_failed(
            failure_category=driver.ERROR_FIXTURE,
            failure_message="fixture build failed",
            failure_traceback="trace",
        )
        snapshot = recorder.snapshot()
        assert snapshot["phase"] == "failed"
        assert snapshot["failure_category"] == driver.ERROR_FIXTURE
        assert snapshot["failure_message"] == "fixture build failed"
        assert snapshot["failure_traceback"] == "trace"

    def test_mark_failed_persists_failure_metadata(
        self, driver, tmp_path: Path
    ) -> None:
        recorder = self._make_recorder(driver, tmp_path)
        recorder.checkpoint("revision_verified")
        recorder.mark_failed(
            failure_category=driver.ERROR_FIXTURE,
            failure_message="fixture build failed",
        )
        progress_path = tmp_path / "progress.json"
        loaded = json.loads(progress_path.read_text(encoding="utf-8"))
        assert loaded["phase"] == "failed"
        assert loaded["failure_category"] == driver.ERROR_FIXTURE
        assert loaded["failure_message"] == "fixture build failed"
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
        self, driver, tmp_path: Path
    ) -> None:
        """Each checkpoint resets phase_started_at so phase_elapsed_seconds
        measures only the current phase."""
        import time

        recorder = self._make_recorder(driver, tmp_path)
        recorder.checkpoint("revision_verified")
        time.sleep(0.05)
        recorder.checkpoint("database_initialized")
        snapshot = recorder.snapshot()
        # phase_elapsed_seconds is for the new phase, should be near zero.
        assert snapshot["phase_elapsed_seconds"] >= 0.0
        # total_elapsed_seconds is anchored to recorder creation.
        assert snapshot["total_elapsed_seconds"] >= snapshot["phase_elapsed_seconds"]


# ---------------------------------------------------------------------------
# _atomic_write_json
# ---------------------------------------------------------------------------

class TestAtomicWriteJson:
    """Tests for the atomic JSON write helper."""

    def test_creates_parent_directories(self, driver, tmp_path: Path) -> None:
        output = tmp_path / "deeply" / "nested" / "dir" / "result.json"
        driver._atomic_write_json(output, {"key": "value"})
        assert output.is_file()

    def test_writes_valid_json(self, driver, tmp_path: Path) -> None:
        output = tmp_path / "result.json"
        payload = {"schema_version": 1, "metrics": {"a": [1, 2, 3]}}
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
# Format time helper (lives in the shared benchmark_fixture module)
# ---------------------------------------------------------------------------

class TestFormatTime:
    """Tests for the time formatting helper in the shared fixture module.

    ``format_time`` moved from the driver to ``benchmark_fixture`` so both
    product and WebView drivers share the same formatting logic.
    """

    def test_midnight(self, driver) -> None:
        from scripts.ci.benchmark_fixture import format_time
        assert format_time("2026-07-15", 0) == "2026-07-15 00:00:00"

    def test_nine_am(self, driver) -> None:
        from scripts.ci.benchmark_fixture import format_time
        assert format_time("2026-07-15", 32400) == "2026-07-15 09:00:00"

    def test_ten_pm(self, driver) -> None:
        from scripts.ci.benchmark_fixture import format_time
        assert format_time("2026-07-15", 79200) == "2026-07-15 22:00:00"

    def test_with_minutes_and_seconds(self, driver) -> None:
        from scripts.ci.benchmark_fixture import format_time
        assert (
            format_time("2026-07-15", 36665)
            == "2026-07-15 10:11:05"
        )


# ---------------------------------------------------------------------------
# main() — argument validation
# ---------------------------------------------------------------------------

class TestMainArguments:
    """Tests for main()'s argument parsing via sys.argv.

    The parser is built inline in ``main()``, so these tests invoke
    ``main()`` with various argv and check the exit code.  When the
    target root is invalid, main() exits before importing any product
    modules, so these tests are hermetic.
    """

    def test_missing_target_root_raises_system_exit(
        self, driver, tmp_path: Path, monkeypatch
    ) -> None:
        """Missing --target-root must cause argparse to exit."""
        monkeypatch.setattr(sys, "argv", [
            "product_benchmark_driver.py",
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
            "product_benchmark_driver.py",
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
            "product_benchmark_driver.py",
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
            "product_benchmark_driver.py",
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
            "product_benchmark_driver.py",
            "--target-root", str(file_path),
            "--revision", "abc123",
            "--output-dir", str(tmp_path / "out"),
        ])
        exit_code = driver.main()
        assert exit_code == driver._EXIT_INPUT_SCHEMA


# ---------------------------------------------------------------------------
# main() — --scenario routing
# ---------------------------------------------------------------------------

class TestScenarioRouting:
    """Tests for the ``--scenario`` argument and its routing.

    ``--scenario`` is NOT required (defaults to ``None``).  When provided,
    ``main()`` runs a single scenario in-process (CI path).  When omitted,
    ``main()`` runs the local-only convenience wrapper (NOT used by CI).
    """

    def test_scenario_arg_routes_to_single_scenario(
        self, driver, tmp_path: Path, monkeypatch
    ) -> None:
        """When --scenario is provided, _run_single_scenario is called."""
        calls: dict[str, dict] = {}

        def stub_single(**kwargs):
            calls["single"] = kwargs
            return 0

        def stub_wrapper(**kwargs):
            calls["wrapper"] = kwargs
            return 0

        monkeypatch.setattr(driver, "_run_single_scenario", stub_single)
        monkeypatch.setattr(driver, "_run_local_wrapper", stub_wrapper)
        monkeypatch.setattr(sys, "argv", [
            "product_benchmark_driver.py",
            "--target-root", str(tmp_path),
            "--revision", "abc123",
            "--output-dir", str(tmp_path / "out"),
            "--scenario", "20k_activities",
        ])
        exit_code = driver.main()
        assert exit_code == 0
        assert "single" in calls
        assert "wrapper" not in calls
        assert calls["single"]["scenario"] == "20k_activities"
        assert calls["single"]["profile"] == "full"

    def test_no_scenario_arg_routes_to_local_wrapper(
        self, driver, tmp_path: Path, monkeypatch
    ) -> None:
        """When --scenario is NOT provided, _run_local_wrapper is called.

        ``--scenario`` defaults to ``None``; CI never uses this path.
        """
        calls: dict[str, dict] = {}

        def stub_single(**kwargs):
            calls["single"] = kwargs
            return 0

        def stub_wrapper(**kwargs):
            calls["wrapper"] = kwargs
            return 0

        monkeypatch.setattr(driver, "_run_single_scenario", stub_single)
        monkeypatch.setattr(driver, "_run_local_wrapper", stub_wrapper)
        monkeypatch.setattr(sys, "argv", [
            "product_benchmark_driver.py",
            "--target-root", str(tmp_path),
            "--revision", "abc123",
            "--output-dir", str(tmp_path / "out"),
        ])
        exit_code = driver.main()
        assert exit_code == 0
        assert "wrapper" in calls
        assert "single" not in calls
        # The wrapper receives the full scenario tuple.
        assert tuple(calls["wrapper"]["scenarios"]) == tuple(
            driver._SCENARIOS.keys()
        )

    def test_invalid_scenario_choice_rejected_by_argparse(
        self, driver, tmp_path: Path, monkeypatch
    ) -> None:
        """An unknown --scenario value must be rejected by argparse."""
        monkeypatch.setattr(sys, "argv", [
            "product_benchmark_driver.py",
            "--target-root", str(tmp_path),
            "--revision", "abc123",
            "--output-dir", str(tmp_path / "out"),
            "--scenario", "not_a_real_scenario",
        ])
        with pytest.raises(SystemExit):
            driver.main()

    def test_invalid_profile_choice_rejected_by_argparse(
        self, driver, tmp_path: Path, monkeypatch
    ) -> None:
        """An unknown --profile value must be rejected by argparse."""
        monkeypatch.setattr(sys, "argv", [
            "product_benchmark_driver.py",
            "--target-root", str(tmp_path),
            "--revision", "abc123",
            "--output-dir", str(tmp_path / "out"),
            "--profile", "ultra",
        ])
        with pytest.raises(SystemExit):
            driver.main()

    def test_default_profile_is_full(
        self, driver, tmp_path: Path, monkeypatch
    ) -> None:
        """The default --profile is 'full' (the real performance gate)."""
        captured: dict[str, object] = {}

        def stub_single(**kwargs):
            captured.update(kwargs)
            return 0

        monkeypatch.setattr(driver, "_run_single_scenario", stub_single)
        monkeypatch.setattr(sys, "argv", [
            "product_benchmark_driver.py",
            "--target-root", str(tmp_path),
            "--revision", "abc123",
            "--output-dir", str(tmp_path / "out"),
            "--scenario", "20k_activities",
        ])
        driver.main()
        assert captured["profile"] == "full"


# ---------------------------------------------------------------------------
# Local wrapper — exists but is NOT CI
# ---------------------------------------------------------------------------

class TestLocalWrapper:
    """The local wrapper exists for developer convenience only.

    CI uses matrix jobs so each scenario runs as an independent runner
    with its own progress/result/failure contract.  The local wrapper
    does NOT own any artifact used by the comparison layer.
    """

    def test_local_wrapper_function_exists(self, driver) -> None:
        assert hasattr(driver, "_run_local_wrapper")
        assert callable(driver._run_local_wrapper)

    def test_local_wrapper_writes_only_convenience_summary(
        self, driver
    ) -> None:
        """The wrapper writes only ``local-wrapper-summary.json`` —
        it never writes ``result.json`` (that is owned by single-scenario
        invocations).  The wrapper may CHECK for result.json to detect
        whether a scenario succeeded, but it never produces one itself.
        """
        source = inspect.getsource(driver._run_local_wrapper)
        assert "local-wrapper-summary.json" in source
        # The only _atomic_write_json call in the wrapper is for the
        # convenience summary — never for result.json or failure.json.
        assert '_atomic_write_json(output_dir / "result.json"' not in source
        assert '_atomic_write_json(output_dir / "failure.json"' not in source
        assert (
            '_atomic_write_json(output_dir / "local-wrapper-summary.json"'
            in source
        )

    def test_local_wrapper_documents_non_ci_status(self, driver) -> None:
        """The wrapper must be documented as NOT used by CI."""
        source = inspect.getsource(driver._run_local_wrapper)
        assert (
            "CI does NOT use this artifact" in source
            or "CI never" in source
            or "NOT used by CI" in source
        ), "local wrapper must document that CI does not use it"

    def test_local_wrapper_does_not_call_run_single_scenario_in_process(
        self, driver
    ) -> None:
        """The wrapper runs scenarios in subprocesses, not in-process —
        so a scenario crash cannot corrupt the wrapper's process state."""
        source = inspect.getsource(driver._run_local_wrapper)
        assert "subprocess.run" in source
        assert "_run_single_scenario(" not in source
