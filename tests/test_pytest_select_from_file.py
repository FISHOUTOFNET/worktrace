"""Unit tests for the pytest_select_from_file plugin.

Verifies the fail-closed contract: a missing or mismatched selection file
must raise ``pytest.UsageError`` so a test rename cannot silently reduce
the common-suite to a partial subset.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.contract, pytest.mark.parallel_safe]

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "scripts" / "pytest_select_from_file.py"


def _run_pytest_with_selection(
    tmp_path: Path,
    *,
    selection_file: Path | None,
    extra_args: list[str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run pytest on a tiny synthetic test file with the selection plugin."""
    synthetic = tmp_path / "test_synthetic_select.py"
    synthetic.write_text(
        "\n".join(
            [
                "def test_alpha(): pass",
                "def test_beta(): pass",
                "def test_gamma(): pass",
            ]
        ),
        encoding="utf-8",
    )
    env = dict(os.environ)
    # The plugin is loaded by module name, so scripts/ must be on sys.path.
    scripts_dir = str(ROOT / "scripts")
    existing_path = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        f"{scripts_dir};{existing_path}" if existing_path else scripts_dir
    )
    if selection_file is not None:
        env["WORKTRACE_SELECT_FILE"] = str(selection_file)
    else:
        env.pop("WORKTRACE_SELECT_FILE", None)

    cmd = [
        sys.executable,
        "-m",
        "pytest",
        str(synthetic),
        "-p",
        "no:cacheprovider",
        "-p",
        "pytest_select_from_file",
        "-q",
        "--tb=short",
        "--color=no",
    ]
    if extra_args:
        cmd.extend(extra_args)
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        env=env,
        cwd=str(ROOT),
        check=False,
    )


def test_no_env_var_runs_all_tests(tmp_path: Path) -> None:
    """Without WORKTRACE_SELECT_FILE, the plugin is a no-op and all tests run."""
    result = _run_pytest_with_selection(tmp_path, selection_file=None)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "3 passed" in result.stdout


def test_selection_file_filters_to_listed_tests(tmp_path: Path) -> None:
    """A selection file listing 2 of 3 tests must run exactly those 2."""
    selection = tmp_path / "selection.txt"
    selection.write_text(
        "\n".join(
            [
                "test_synthetic_select.py::test_alpha",
                "test_synthetic_select.py::test_beta",
            ]
        ),
        encoding="utf-8",
    )
    result = _run_pytest_with_selection(tmp_path, selection_file=selection)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "2 passed" in result.stdout


def test_missing_selection_file_fails_closed(tmp_path: Path) -> None:
    """A missing selection file must fail, not silently run everything."""
    missing = tmp_path / "does-not-exist.txt"
    result = _run_pytest_with_selection(tmp_path, selection_file=missing)
    assert result.returncode != 0, "missing selection file must fail"
    combined = (result.stdout + "\n" + result.stderr).lower()
    assert "missing file" in combined or "usageerror" in combined


def test_empty_selection_file_fails_closed(tmp_path: Path) -> None:
    """An empty selection file must fail, not silently run nothing."""
    empty = tmp_path / "empty.txt"
    empty.write_text("\n", encoding="utf-8")
    result = _run_pytest_with_selection(tmp_path, selection_file=empty)
    assert result.returncode != 0, "empty selection file must fail"
    combined = (result.stdout + "\n" + result.stderr).lower()
    assert "empty" in combined or "usageerror" in combined


def test_selection_file_with_missing_node_ids_fails_closed(tmp_path: Path) -> None:
    """If the selection file lists a node ID that was not collected, the
    plugin must fail so a test rename surfaces as an explicit error.
    """
    selection = tmp_path / "stale.txt"
    selection.write_text(
        "\n".join(
            [
                "test_synthetic_select.py::test_alpha",
                "test_synthetic_select.py::test_renamed_or_removed",
            ]
        ),
        encoding="utf-8",
    )
    result = _run_pytest_with_selection(tmp_path, selection_file=selection)
    assert result.returncode != 0, "stale selection file must fail"
    combined = (result.stdout + "\n" + result.stderr).lower()
    assert "not collected" in combined or "usageerror" in combined


def test_selection_file_ignores_comments_and_blanks(tmp_path: Path) -> None:
    """Lines starting with ``#`` and blank lines must be ignored."""
    selection = tmp_path / "with-comments.txt"
    selection.write_text(
        "\n".join(
            [
                "# This is a comment",
                "",
                "test_synthetic_select.py::test_alpha",
                "# Another comment",
                "test_synthetic_select.py::test_beta",
            ]
        ),
        encoding="utf-8",
    )
    result = _run_pytest_with_selection(tmp_path, selection_file=selection)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "2 passed" in result.stdout
