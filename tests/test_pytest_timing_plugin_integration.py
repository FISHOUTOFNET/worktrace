"""Integration tests for the pytest_timing_plugin harness plugin.

Each test spawns pytest in a subprocess with the timing plugin loaded
from the HEAD-owned ``.ci-harness/`` directory and verifies:

* exact pytest ``report.nodeid`` recording (matches ``--collect-only -q``);
* setup / call / teardown durations;
* module-level, class-level, and parametrized test node IDs;
* passed / skipped / xfailed / failed outcomes;
* the structured timing JSON schema (schema_version, revision, plugin_path,
  selection_hash, counts, timestamps, exit_code, tests array);
* fail-closed behavior when ``--timing-json`` or
  ``WORKTRACE_TIMING_REVISION`` is missing;
* the plugin is loaded from the harness directory, not the worktree.

Marked as integration/contract because each test spawns a subprocess.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.contract, pytest.mark.parallel_safe]

ROOT = Path(__file__).resolve().parents[1]
HARNESS_DIR = ROOT / ".ci-harness"


def _run_pytest_with_timing(
    tmp_path: Path,
    *,
    test_file_content: str,
    timing_json_path: Path | None = None,
    revision: str = "test-revision-12345",
    extra_args: list[str] | None = None,
    selection_file: Path | None = None,
    omit_timing_json: bool = False,
    omit_revision: bool = False,
) -> subprocess.CompletedProcess[str]:
    """Run pytest on a synthetic test file with the timing plugin loaded.

    Returns the CompletedProcess.  The timing JSON (if produced) is
    written to ``timing_json_path``.
    """
    synthetic = tmp_path / "test_synthetic_timing.py"
    synthetic.write_text(test_file_content, encoding="utf-8")
    # Anchor pytest's rootdir to tmp_path so collected node IDs are
    # relative (e.g. ``test_synthetic_timing.py::test_alpha``) and match
    # the selection file format.
    (tmp_path / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")

    env = dict(os.environ)
    # Prepend the harness directory so -p pytest_timing_plugin finds it.
    existing_path = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        f"{HARNESS_DIR};{existing_path}" if existing_path else str(HARNESS_DIR)
    )

    if not omit_revision:
        env["WORKTRACE_TIMING_REVISION"] = revision
    else:
        env.pop("WORKTRACE_TIMING_REVISION", None)

    if selection_file is not None:
        env["WORKTRACE_SELECT_FILE"] = str(selection_file)
    else:
        env.pop("WORKTRACE_SELECT_FILE", None)

    cmd = [
        sys.executable,
        "-m",
        "pytest",
        "test_synthetic_timing.py",
        "-p",
        "no:cacheprovider",
        "-p",
        "pytest_timing_plugin",
        "-q",
        "--tb=short",
        "--color=no",
    ]
    if timing_json_path is not None and not omit_timing_json:
        cmd.extend(["--timing-json", str(timing_json_path)])
    if extra_args:
        cmd.extend(extra_args)

    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        env=env,
        cwd=str(tmp_path),
        check=False,
    )


def _load_timing_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _collect_only_nodeids(tmp_path: Path, test_file_content: str) -> list[str]:
    """Run pytest --collect-only -q to get the canonical node IDs."""
    synthetic = tmp_path / "test_synthetic_timing.py"
    synthetic.write_text(test_file_content, encoding="utf-8")
    (tmp_path / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "test_synthetic_timing.py",
            "--collect-only",
            "-q",
            "--color=no",
        ],
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
        check=False,
    )
    lines = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if line and "::" in line and not line.startswith("test_synthetic_timing.py::"):
            # pytest may prefix with the file name; extract just the node ID.
            pass
        if "::" in line:
            lines.append(line)
    return lines


# ---------------------------------------------------------------------------
# Basic timing JSON structure
# ---------------------------------------------------------------------------

class TestTimingJsonSchema:
    """Verify the timing JSON has the required schema fields."""

    _SIMPLE_TEST = "\n".join([
        "def test_alpha(): pass",
        "def test_beta(): pass",
    ])

    def test_json_has_required_envelope_fields(
        self, tmp_path: Path
    ) -> None:
        timing_path = tmp_path / "timing.json"
        result = _run_pytest_with_timing(
            tmp_path,
            test_file_content=self._SIMPLE_TEST,
            timing_json_path=timing_path,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert timing_path.is_file(), "timing.json was not written"
        payload = _load_timing_json(timing_path)

        for field in (
            "schema_version",
            "revision",
            "worktree_root",
            "plugin_path",
            "selection_hash",
            "python_version",
            "pytest_version",
            "worker_count",
            "marker_expression",
            "selected_count",
            "collected_count",
            "deselected_count",
            "started_at",
            "finished_at",
            "exit_code",
            "tests",
        ):
            assert field in payload, f"missing field: {field}"

        assert payload["schema_version"] == 1
        assert payload["revision"] == "test-revision-12345"
        assert payload["exit_code"] == 0
        assert payload["selected_count"] == 2
        assert payload["collected_count"] >= 2
        assert isinstance(payload["tests"], list)

    def test_plugin_path_points_at_harness_directory(
        self, tmp_path: Path
    ) -> None:
        """The plugin_path field must point at the .ci-harness directory,
        not the worktree."""
        timing_path = tmp_path / "timing.json"
        result = _run_pytest_with_timing(
            tmp_path,
            test_file_content=self._SIMPLE_TEST,
            timing_json_path=timing_path,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        payload = _load_timing_json(timing_path)
        plugin_path = payload["plugin_path"]
        assert ".ci-harness" in plugin_path
        assert "pytest_timing_plugin.py" in plugin_path

    def test_no_tmp_file_left_behind(
        self, tmp_path: Path
    ) -> None:
        """The atomic write must not leave a .tmp file behind."""
        timing_path = tmp_path / "timing.json"
        result = _run_pytest_with_timing(
            tmp_path,
            test_file_content=self._SIMPLE_TEST,
            timing_json_path=timing_path,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        tmp_files = list(tmp_path.glob("timing*.tmp"))
        assert len(tmp_files) == 0


# ---------------------------------------------------------------------------
# Exact node ID recording
# ---------------------------------------------------------------------------

class TestExactNodeIds:
    """Verify the plugin records exact pytest node IDs."""

    _MIXED_TEST = "\n".join([
        "import pytest",
        "",
        "def test_module_level(): pass",
        "",
        "class TestClass:",
        "    def test_method(self): pass",
        "",
        "@pytest.mark.parametrize('val', [1, 2])",
        "def test_parametrized(val): pass",
    ])

    def test_nodeids_match_collect_only(
        self, tmp_path: Path
    ) -> None:
        """The node IDs in timing.json must exactly match the IDs from
        ``pytest --collect-only -q``."""
        timing_path = tmp_path / "timing.json"
        result = _run_pytest_with_timing(
            tmp_path,
            test_file_content=self._MIXED_TEST,
            timing_json_path=timing_path,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        payload = _load_timing_json(timing_path)
        timing_nodeids = {t["nodeid"] for t in payload["tests"]}

        # Collect-only to get canonical node IDs.
        collect_result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "test_synthetic_timing.py",
                "--collect-only",
                "-q",
                "--color=no",
            ],
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
            check=False,
        )
        collect_nodeids = set()
        for line in collect_result.stdout.splitlines():
            line = line.strip()
            if "::" in line:
                collect_nodeids.add(line)

        assert timing_nodeids == collect_nodeids, (
            f"timing nodeids: {timing_nodeids}\n"
            f"collect nodeids: {collect_nodeids}"
        )

    def test_module_level_test_recorded(
        self, tmp_path: Path
    ) -> None:
        timing_path = tmp_path / "timing.json"
        result = _run_pytest_with_timing(
            tmp_path,
            test_file_content="def test_module_level(): pass",
            timing_json_path=timing_path,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        payload = _load_timing_json(timing_path)
        nodeids = {t["nodeid"] for t in payload["tests"]}
        assert "test_synthetic_timing.py::test_module_level" in nodeids

    def test_class_method_test_recorded(
        self, tmp_path: Path
    ) -> None:
        timing_path = tmp_path / "timing.json"
        test_content = "\n".join([
            "class TestClass:",
            "    def test_method(self): pass",
        ])
        result = _run_pytest_with_timing(
            tmp_path,
            test_file_content=test_content,
            timing_json_path=timing_path,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        payload = _load_timing_json(timing_path)
        nodeids = {t["nodeid"] for t in payload["tests"]}
        assert "test_synthetic_timing.py::TestClass::test_method" in nodeids

    def test_parametrized_test_recorded_with_params(
        self, tmp_path: Path
    ) -> None:
        """Parametrized test node IDs must include the parameter values
        in brackets, exactly as pytest reports them."""
        timing_path = tmp_path / "timing.json"
        test_content = "\n".join([
            "import pytest",
            "",
            "@pytest.mark.parametrize('val', [1, 2])",
            "def test_parametrized(val): pass",
        ])
        result = _run_pytest_with_timing(
            tmp_path,
            test_file_content=test_content,
            timing_json_path=timing_path,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        payload = _load_timing_json(timing_path)
        nodeids = {t["nodeid"] for t in payload["tests"]}
        assert "test_synthetic_timing.py::test_parametrized[1]" in nodeids
        assert "test_synthetic_timing.py::test_parametrized[2]" in nodeids


# ---------------------------------------------------------------------------
# Setup/call/teardown durations and outcomes
# ---------------------------------------------------------------------------

class TestStepDurations:
    """Verify setup/call/teardown durations and outcome are recorded."""

    def test_passed_test_has_all_phases_and_passed_outcome(
        self, tmp_path: Path
    ) -> None:
        timing_path = tmp_path / "timing.json"
        result = _run_pytest_with_timing(
            tmp_path,
            test_file_content="def test_alpha(): pass",
            timing_json_path=timing_path,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        payload = _load_timing_json(timing_path)
        entry = payload["tests"][0]
        for field in ("setup_seconds", "call_seconds", "teardown_seconds",
                       "total_seconds", "outcome", "nodeid"):
            assert field in entry
        assert entry["outcome"] == "passed"
        assert entry["total_seconds"] >= 0.0

    def test_skipped_test_recorded_as_skipped(
        self, tmp_path: Path
    ) -> None:
        timing_path = tmp_path / "timing.json"
        test_content = "\n".join([
            "import pytest",
            "",
            "@pytest.mark.skip(reason='testing skip')",
            "def test_skipped(): pass",
        ])
        result = _run_pytest_with_timing(
            tmp_path,
            test_file_content=test_content,
            timing_json_path=timing_path,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        payload = _load_timing_json(timing_path)
        entry = payload["tests"][0]
        assert entry["outcome"] == "skipped"

    def test_xfailed_test_recorded_as_xfailed(
        self, tmp_path: Path
    ) -> None:
        timing_path = tmp_path / "timing.json"
        test_content = "\n".join([
            "import pytest",
            "",
            "@pytest.mark.xfail(reason='testing xfail')",
            "def test_xfailed(): assert False",
        ])
        result = _run_pytest_with_timing(
            tmp_path,
            test_file_content=test_content,
            timing_json_path=timing_path,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        payload = _load_timing_json(timing_path)
        entry = payload["tests"][0]
        assert entry["outcome"] == "xfailed"

    def test_failed_test_recorded_as_failed(
        self, tmp_path: Path
    ) -> None:
        timing_path = tmp_path / "timing.json"
        test_content = "\n".join([
            "def test_failed(): assert False, 'intentional failure'",
        ])
        result = _run_pytest_with_timing(
            tmp_path,
            test_file_content=test_content,
            timing_json_path=timing_path,
        )
        # pytest exits 1 for a failed test.
        assert result.returncode != 0
        assert timing_path.is_file(), "timing.json must still be written on failure"
        payload = _load_timing_json(timing_path)
        entry = payload["tests"][0]
        assert entry["outcome"] == "failed"
        # The session-level exit_code must be non-zero for a failed run.
        assert payload["exit_code"] != 0


# ---------------------------------------------------------------------------
# Fail-closed behavior
# ---------------------------------------------------------------------------

class TestFailClosed:
    """Verify the plugin fails-closed on misconfiguration."""

    def test_missing_timing_json_arg_raises_usage_error(
        self, tmp_path: Path
    ) -> None:
        """When --timing-json is not provided AND WORKTRACE_TIMING_JSON
        env var is not set, the plugin must raise pytest.UsageError."""
        result = _run_pytest_with_timing(
            tmp_path,
            test_file_content="def test_alpha(): pass",
            timing_json_path=None,
            omit_timing_json=True,
        )
        assert result.returncode != 0
        combined = (result.stdout + "\n" + result.stderr).lower()
        assert "usageerror" in combined or "timing-json" in combined

    def test_missing_revision_env_raises_usage_error(
        self, tmp_path: Path
    ) -> None:
        """When WORKTRACE_TIMING_REVISION is not set, the plugin must
        raise pytest.UsageError."""
        timing_path = tmp_path / "timing.json"
        result = _run_pytest_with_timing(
            tmp_path,
            test_file_content="def test_alpha(): pass",
            timing_json_path=timing_path,
            omit_revision=True,
        )
        assert result.returncode != 0
        combined = (result.stdout + "\n" + result.stderr).lower()
        assert "usageerror" in combined or "revision" in combined


# ---------------------------------------------------------------------------
# Selection hash and counts
# ---------------------------------------------------------------------------

class TestSelectionAndCounts:
    """Verify selection hash and collected/selected/deselected counts."""

    def test_no_selection_yields_empty_hash(
        self, tmp_path: Path
    ) -> None:
        timing_path = tmp_path / "timing.json"
        result = _run_pytest_with_timing(
            tmp_path,
            test_file_content="\n".join([
                "def test_alpha(): pass",
                "def test_beta(): pass",
                "def test_gamma(): pass",
            ]),
            timing_json_path=timing_path,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        payload = _load_timing_json(timing_path)
        assert payload["selection_hash"] == ""
        assert payload["selected_count"] == 3
        assert payload["collected_count"] >= 3
        assert payload["deselected_count"] == 0

    def test_marker_expression_recorded(
        self, tmp_path: Path
    ) -> None:
        """When -m is passed, the marker_expression field records it."""
        timing_path = tmp_path / "timing.json"
        test_content = "\n".join([
            "import pytest",
            "",
            "@pytest.mark.slow",
            "def test_slow(): pass",
            "",
            "def test_fast(): pass",
        ])
        result = _run_pytest_with_timing(
            tmp_path,
            test_file_content=test_content,
            timing_json_path=timing_path,
            extra_args=["-m", "slow"],
        )
        assert result.returncode == 0, result.stdout + result.stderr
        payload = _load_timing_json(timing_path)
        assert payload["marker_expression"] == "slow"
        assert payload["selected_count"] == 1
        assert payload["deselected_count"] >= 1
