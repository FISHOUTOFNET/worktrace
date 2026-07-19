from __future__ import annotations

import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

pytestmark = [pytest.mark.contract, pytest.mark.integration, pytest.mark.db]

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "pytest_diagnostics.py"
WORKFLOW = ROOT / ".github" / "workflows" / "_validation.yml"
CI_WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"


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
            detail = (
                "tests/test_synthetic.py:10: in test_failure\n"
                "worktrace/db.py:412: in initialize\n"
                f"E {message}\nTRACEBACK-SENTINEL-{index:02d}"
            )
        else:
            message = "AttributeError: retry_pending_inference"
            detail = (
                "tests/test_synthetic.py:20: in test_failure\n"
                "worktrace/runtime/app_runtime.py:90: in start\n"
                f"E {message}\nTRACEBACK-SENTINEL-{index:02d}"
            )
        failure = ET.SubElement(case, "failure", message=message)
        failure.text = detail
    ET.ElementTree(suite).write(path, encoding="utf-8", xml_declaration=True)


def test_diagnostics_emit_all_failures_and_grouped_api_contract(tmp_path: Path) -> None:
    junit = tmp_path / "pytest-junit.xml"
    log = tmp_path / "pytest.log"
    output_dir = tmp_path / "diagnostics"
    summary = tmp_path / "summary.md"
    github_output = tmp_path / "github-output.txt"
    _write_junit(junit)
    log.write_text("pytest failed\n", encoding="utf-8")

    env = os.environ.copy()
    env["GITHUB_OUTPUT"] = str(github_output)
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--stage",
            "pytest",
            "--junit",
            str(junit),
            "--log",
            str(log),
            "--output-dir",
            str(output_dir),
            "--revision",
            "a" * 40,
            "--artifact-name",
            "validation-diagnostics-test",
            "--summary",
            str(summary),
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "=== WORKTRACE_CI_DIAGNOSTICS_V1_BEGIN ===" in result.stdout
    assert "=== WORKTRACE_CI_DIAGNOSTICS_V1_END ===" in result.stdout
    assert "failure_count=35" in result.stdout
    assert "root_cause_count=2" in result.stdout
    assert "[35/35] tests.synthetic::test_failure_35" in result.stdout

    payload = json.loads((output_dir / "diagnostics.json").read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert payload["failed_stage"] == "pytest"
    assert payload["counts"] == {
        "total": 35,
        "passed": 0,
        "failed": 35,
        "errors": 0,
        "skipped": 0,
    }
    assert len(payload["failures"]) == 35
    assert [len(group["affected_tests"]) for group in payload["root_cause_groups"]] == [30, 5]
    assert "TRACEBACK-SENTINEL-35" in (
        output_dir / "failure-details.txt"
    ).read_text(encoding="utf-8")
    assert "problem_count=35" in github_output.read_text(encoding="utf-8")


def test_diagnostics_fallback_is_persisted_and_api_readable(tmp_path: Path) -> None:
    log = tmp_path / "compile.log"
    output_dir = tmp_path / "diagnostics"
    log.write_text("SyntaxError: invalid syntax\n", encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--stage",
            "compile",
            "--log",
            str(log),
            "--output-dir",
            str(output_dir),
            "--revision",
            "b" * 40,
            "--artifact-name",
            "validation-diagnostics-compile",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "failed_stage=compile" in result.stdout
    assert "diagnostics_available=false" in result.stdout
    assert "SyntaxError: invalid syntax" in result.stdout
    payload = json.loads((output_dir / "diagnostics.json").read_text(encoding="utf-8"))
    assert payload["failed_stage"] == "compile"
    assert payload["diagnostics_available"] is False


def test_ci_has_one_diagnostic_owner_and_no_self_log_replay() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    ci_workflow = CI_WORKFLOW.read_text(encoding="utf-8")

    assert "gh api" not in workflow
    assert "actions: read" not in workflow
    assert "python_failure_manifest" not in workflow
    assert "python_failure_details" not in workflow
    assert "matrix:" not in workflow
    assert workflow.count("validation-diagnostics-${{ inputs.revision }}") == 2
    assert "actions/upload-artifact@v6" in workflow
    assert "retention-days: 3" in workflow
    assert "if-no-files-found: warn" in workflow
    assert "run_node_tests: true" in ci_workflow
    assert "run_build_smoke: true" in ci_workflow
    assert "actions: read" not in ci_workflow
