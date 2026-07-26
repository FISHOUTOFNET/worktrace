"""Unit tests for the HEAD-owned product benchmark driver.

Covers the pure-Python functions in ``scripts/ci/product_benchmark_driver.py``:
target-root path isolation, module verification, deterministic fixture hash,
time formatting, atomic JSON writes, runner metadata, and argument parsing.

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
import json
import os
import sys
from pathlib import Path
from typing import Any

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

    def test_schema_version_is_1(self, driver) -> None:
        assert driver._SCHEMA_VERSION == 1

    def test_driver_version_is_string(self, driver) -> None:
        assert isinstance(driver._DRIVER_VERSION, str)
        assert len(driver._DRIVER_VERSION) > 0

    def test_exit_codes_are_distinct_and_nonzero(self, driver) -> None:
        assert driver._EXIT_INPUT_SCHEMA == 2
        assert driver._EXIT_EXECUTION == 3
        assert driver._EXIT_INPUT_SCHEMA != driver._EXIT_EXECUTION

    def test_fixture_parameters_are_fixed(self, driver) -> None:
        """The fixture parameters must be deterministic (no RNG)."""
        assert driver._REPORT_DATE == "2026-07-15"
        assert driver._DAY_START_SECONDS == 9 * 3600
        assert driver._SPAN_SECONDS == 13 * 3600


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


class TestFixtureHash:
    """Tests for the deterministic fixture hash."""

    def test_hash_is_deterministic(self, driver) -> None:
        """The fixture hash must be the same across calls."""
        h1 = driver._fixture_hash()
        h2 = driver._fixture_hash()
        assert h1 == h2

    def test_hash_is_sha256_hex(self, driver) -> None:
        """The fixture hash must be a 64-character hex string."""
        h = driver._fixture_hash()
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    def test_hash_encodes_fixture_parameters(self, driver) -> None:
        """The hash encodes the report date, day start, span, and scenario
        sizes so any change to the fixture parameters produces a
        different hash."""
        import hashlib
        expected_payload = json.dumps(
            {
                "report_date": driver._REPORT_DATE,
                "day_start_seconds": driver._DAY_START_SECONDS,
                "span_seconds": driver._SPAN_SECONDS,
                "scenarios": {
                    "20k_activities": {"activity_count": 20000},
                    "10k_contributions": {"contribution_count": 10000},
                },
            },
            sort_keys=True,
        ).encode("utf-8")
        expected = hashlib.sha256(expected_payload).hexdigest()
        assert driver._fixture_hash() == expected


class TestFormatTime:
    """Tests for the time formatting helper."""

    def test_midnight(self, driver) -> None:
        assert driver._format_time("2026-07-15", 0) == "2026-07-15 00:00:00"

    def test_nine_am(self, driver) -> None:
        assert driver._format_time("2026-07-15", 32400) == "2026-07-15 09:00:00"

    def test_ten_pm(self, driver) -> None:
        assert driver._format_time("2026-07-15", 79200) == "2026-07-15 22:00:00"

    def test_with_minutes_and_seconds(self, driver) -> None:
        assert (
            driver._format_time("2026-07-15", 36665)
            == "2026-07-15 10:11:05"
        )


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
# main() — argument validation
# ---------------------------------------------------------------------------

class TestMainArguments:
    """Tests for main()'s argument parsing via sys.argv.

    The parser is built inline in ``main()``, so these tests invoke
    ``main()`` with various argv and check the exit code.  When the
    target root is invalid, main() exits before importing any product
    modules, so these tests are hermetic.
    """

    def test_missing_required_args_raises_system_exit(
        self, driver, monkeypatch
    ) -> None:
        """Missing --target-root must cause argparse to exit."""
        monkeypatch.setattr(sys, "argv", [
            "product_benchmark_driver.py",
            "--revision", "abc123",
            "--output", "out.json",
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
            "--output", str(tmp_path / "out.json"),
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
            "--output", str(tmp_path / "out.json"),
        ])
        exit_code = driver.main()
        assert exit_code == driver._EXIT_INPUT_SCHEMA
