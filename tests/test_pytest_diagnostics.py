"""Stable failure-diagnostics contracts used by Standard CI."""

from __future__ import annotations

import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

pytestmark = [pytest.mark.contract, pytest.mark.integration, pytest.mark.parallel_safe]

ROOT = Path(__file__).resolve().parents[1]
PRODUCER = ROOT / "scripts" / "pytest_diagnostics.py"
PYTEST_RUNNER = ROOT / "scripts" / "run_pytest_ci.py"
WORKFLOW = ROOT / ".github" / "workflows" / "_validation.yml"


def _write_junit(path: Path) -> None:
    suite = ET.Element("testsuite", tests="2", failures="2")
    for index in range(1, 3):
        case = ET.SubElement(
            suite,
            "testcase",
            classname="tests.synthetic",
            name=f"test_failure_{index}",
        )
        failure = ET.SubElement(
            case,
            "failure",
            message="sqlite3.OperationalError: no such table: activity_inference_job",
        )
        failure.text = (
            "tests/test_synthetic.py:10: in test_failure\n"
            "worktrace/db.py:412: in owner\n"
            f"E sqlite3.OperationalError: no such table: activity_inference_job\n"
            f"TRACEBACK-SENTINEL-{index}"
        )
    ET.ElementTree(suite).write(path, encoding="utf-8", xml_declaration=True)


def _produce(
    tmp_path: Path,
    *,
    stage: str = "pytest",
) -> tuple[Path, subprocess.CompletedProcess[str]]:
    log = tmp_path / f"{stage}.log"
    output = tmp_path / "diagnostics"
    log.write_text(
        "SyntaxError: invalid syntax\n" if stage != "pytest" else "pytest failed\n",
        encoding="utf-8",
    )
    command = [
        sys.executable,
        str(PRODUCER),
        "--stage",
        stage,
        "--log",
        str(log),
        "--output-dir",
        str(output),
        "--revision",
        "a" * 40,
        "--artifact-name",
        "validation-diagnostics-test",
    ]
    if stage == "pytest":
        junit = tmp_path / "pytest-junit.xml"
        _write_junit(junit)
        command[4:4] = ["--junit", str(junit)]
    result = subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return output, result


def test_diagnostics_keep_failure_details_in_artifact_only(tmp_path: Path) -> None:
    output, result = _produce(tmp_path)
    payload = json.loads((output / "diagnostics.json").read_text(encoding="utf-8"))

    assert payload["counts"]["failed"] == 2
    assert len(payload["failures"]) == 2
    assert "TRACEBACK-SENTINEL-2" in payload["failures"][-1]["details"]
    assert "TRACEBACK-SENTINEL-2" in (output / "failure-details.txt").read_text(
        encoding="utf-8"
    )
    assert "diagnostics_artifact_status=ready" in result.stdout
    assert "TRACEBACK-SENTINEL" not in result.stdout
    assert "no such table" not in result.stdout


def test_diagnostics_fallback_keeps_raw_compile_error_in_artifact(tmp_path: Path) -> None:
    output, result = _produce(tmp_path, stage="compile")
    payload = json.loads((output / "diagnostics.json").read_text(encoding="utf-8"))

    assert payload["failed_stage"] == "compile"
    assert payload["diagnostics_available"] is False
    assert "SyntaxError: invalid syntax" in payload["log_tail"]
    assert "SyntaxError: invalid syntax" in (output / "failure-details.txt").read_text(
        encoding="utf-8"
    )
    assert "diagnostics_artifact_status=fallback" in result.stdout
    assert "SyntaxError: invalid syntax" not in result.stdout


def test_pytest_runner_reports_progress_without_echoing_test_failure(tmp_path: Path) -> None:
    synthetic = tmp_path / "test_synthetic_progress.py"
    synthetic.write_text(
        """
def test_passes():
    pass


def test_fails():
    assert False, "SENTINEL_FAILURE"
""".lstrip(),
        encoding="utf-8",
    )
    log = tmp_path / "pytest.log"
    progress = tmp_path / "pytest-progress.json"
    result = subprocess.run(
        [
            sys.executable,
            str(PYTEST_RUNNER),
            "--log",
            str(log),
            "--progress",
            str(progress),
            "--heartbeat-seconds",
            "0.05",
            "--",
            "-q",
            "--tb=short",
            "--color=no",
            str(synthetic),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "pytest_progress status=starting" in result.stdout
    assert "pytest_progress status=finished" in result.stdout
    assert "SENTINEL_FAILURE" not in result.stdout
    assert "SENTINEL_FAILURE" in log.read_text(encoding="utf-8")

    payload = json.loads(progress.read_text(encoding="utf-8"))
    assert payload["status"] == "finished"
    assert payload["completed"] == 2
    assert payload["total"] == 2


def test_standard_ci_uses_full_suite_and_artifact_diagnostics() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "scripts/run_pytest_ci.py" in workflow
    assert "--heartbeat-seconds 60" in workflow
    assert '-m "not benchmark"' in workflow
    assert "name: Generate diagnostic artifact" in workflow
    assert "name: Upload diagnostic artifact" in workflow
    assert "retention-days: 3" in workflow
