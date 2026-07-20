from __future__ import annotations

import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

pytestmark = [pytest.mark.contract, pytest.mark.integration, pytest.mark.db]

ROOT = Path(__file__).resolve().parents[1]
PRODUCER = ROOT / "scripts" / "pytest_diagnostics.py"
PYTEST_RUNNER = ROOT / "scripts" / "run_pytest_ci.py"
RETIRED_RENDERER = ROOT / "scripts" / "render_ci_api_summary.py"
WORKFLOW = ROOT / ".github" / "workflows" / "_validation.yml"


def _write_junit(path: Path, count: int = 35) -> None:
    suite = ET.Element("testsuite", tests=str(count), failures=str(count))
    for index in range(1, count + 1):
        case = ET.SubElement(
            suite,
            "testcase",
            classname="tests.synthetic",
            name=f"test_failure_{index:02d}",
        )
        if index <= 30:
            message = "sqlite3.OperationalError: no such table: activity_inference_job"
            location = "worktrace/db.py:412"
        else:
            message = "AttributeError: retry_pending_inference"
            location = "worktrace/runtime/app_runtime.py:90"
        failure = ET.SubElement(case, "failure", message=message)
        failure.text = (
            f"tests/test_synthetic.py:10: in test_failure\n{location}: in owner\n"
            f"E {message}\nTRACEBACK-SENTINEL-{index:02d}"
        )
    ET.ElementTree(suite).write(path, encoding="utf-8", xml_declaration=True)


def _produce(tmp_path: Path, *, stage: str = "pytest") -> tuple[Path, subprocess.CompletedProcess[str]]:
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


def test_artifact_preserves_all_failures_without_replaying_them_to_stdout(
    tmp_path: Path,
) -> None:
    output, result = _produce(tmp_path)
    payload = json.loads((output / "diagnostics.json").read_text(encoding="utf-8"))

    assert payload["counts"]["failed"] == 35
    assert len(payload["failures"]) == 35
    assert [len(group["affected_tests"]) for group in payload["root_cause_groups"]] == [30, 5]
    assert "TRACEBACK-SENTINEL-35" in payload["failures"][-1]["details"]
    assert "TRACEBACK-SENTINEL-35" in (output / "failure-details.txt").read_text(
        encoding="utf-8"
    )

    assert "diagnostics_artifact_status=ready" in result.stdout
    assert "source=diagnostics.json" in result.stdout
    assert "TRACEBACK-SENTINEL" not in result.stdout
    assert "no such table" not in result.stdout
    assert "retry_pending_inference" not in result.stdout
    assert "ROOT_CAUSE_GROUPS" not in result.stdout


def test_fallback_keeps_raw_error_only_inside_artifact(tmp_path: Path) -> None:
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


def test_pytest_runner_streams_progress_but_keeps_test_output_in_log(tmp_path: Path) -> None:
    synthetic = tmp_path / "test_synthetic_progress.py"
    synthetic.write_text(
        """
import time


def test_passes():
    time.sleep(0.12)


def test_fails():
    time.sleep(0.12)
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
    assert "short test summary info" not in result.stdout
    assert "SENTINEL_FAILURE" in log.read_text(encoding="utf-8")

    payload = json.loads(progress.read_text(encoding="utf-8"))
    assert payload["status"] == "finished"
    assert payload["completed"] == 2
    assert payload["total"] == 2


def test_ci_contract_is_artifact_only_with_bounded_progress() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    producer = PRODUCER.read_text(encoding="utf-8")

    assert "# Business-test diagnostics are artifact-only." in workflow
    assert "scripts/run_pytest_ci.py" in workflow
    assert "--heartbeat-seconds 60" in workflow
    assert '*> "test-results/pytest.log"' not in workflow
    assert 'Get-Content -LiteralPath "test-results/pytest.log"' not in workflow

    assert workflow.count("actions/upload-artifact@v6") == 2
    assert "actions/download-artifact@" not in workflow
    assert "python_diagnostics:" not in workflow
    assert "name: Python failure diagnostics" not in workflow
    assert "api-summary.txt" not in workflow
    assert "render_ci_api_summary.py" not in workflow
    assert not RETIRED_RENDERER.exists()

    assert "name: Generate diagnostic artifact" in workflow
    assert "name: Upload diagnostic artifact" in workflow
    assert "if-no-files-found: error" in workflow
    assert "retention-days: 3" in workflow
    assert "retention-days: 1" in workflow
    assert '--summary "$env:GITHUB_STEP_SUMMARY"' not in workflow

    assert "_emit_protocol" not in producer
    assert "ROOT_CAUSE_GROUPS_BEGIN" not in producer
    assert "GITHUB_OUTPUT" not in producer
    assert "problem_count=" not in producer
    assert "first_failure=" not in producer
