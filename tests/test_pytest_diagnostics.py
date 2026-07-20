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
PRODUCER = ROOT / "scripts" / "pytest_diagnostics.py"
RENDERER = ROOT / "scripts" / "render_ci_api_summary.py"
WORKFLOW = ROOT / ".github" / "workflows" / "_validation.yml"


def _write_junit(path: Path, count: int = 35, *, distinct: bool = False) -> None:
    suite = ET.Element("testsuite", tests=str(count), failures=str(count))
    for index in range(1, count + 1):
        case = ET.SubElement(
            suite,
            "testcase",
            classname="tests.synthetic",
            name=f"test_failure_{index:02d}",
        )
        if distinct:
            message = f"AssertionError: synthetic root cause {index:02d}"
            location = f"worktrace/service_{index:02d}.py:{100 + index}"
        elif index <= 30:
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


def _produce(
    tmp_path: Path,
    *,
    stage: str = "pytest",
    count: int = 35,
    distinct: bool = False,
) -> Path:
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
        _write_junit(junit, count=count, distinct=distinct)
        command[4:4] = ["--junit", str(junit)]
    env = os.environ.copy()
    env["GITHUB_OUTPUT"] = str(tmp_path / "github-output.txt")
    result = subprocess.run(
        command,
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return output


def _render(output: Path, rendered: Path) -> str:
    result = subprocess.run(
        [
            sys.executable,
            str(RENDERER),
            "--input",
            str(output / "diagnostics.json"),
            "--output",
            str(rendered),
            "--max-bytes",
            "65536",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return rendered.read_text(encoding="utf-8")


def test_artifact_preserves_all_failures_and_signature_groups(tmp_path: Path) -> None:
    output = _produce(tmp_path)
    payload = json.loads((output / "diagnostics.json").read_text(encoding="utf-8"))
    assert payload["counts"]["failed"] == 35
    assert len(payload["failures"]) == 35
    assert [len(group["affected_tests"]) for group in payload["root_cause_groups"]] == [30, 5]
    assert "TRACEBACK-SENTINEL-35" in payload["failures"][-1]["details"]
    assert "TRACEBACK-SENTINEL-35" in (output / "failure-details.txt").read_text(encoding="utf-8")


def test_renderer_publishes_complete_compact_root_cause_index(tmp_path: Path) -> None:
    output = _produce(tmp_path)
    rendered = output / "api-summary.txt"
    text = _render(output, rendered)
    assert text.startswith("WORKTRACE_CI_DIAGNOSTICS_V1\n")
    assert "summary_scope=complete_root_cause_index" in text
    assert "machine_source=artifact:diagnostics.json" in text
    assert "failure_signature_group_count=2" in text
    assert "shown_signature_group_count=2" in text
    assert "omitted_signature_group_count=0" in text
    assert text.count("signature_group_json=") == 2
    assert "TRACEBACK-SENTINEL" not in text
    assert "cause_chunk_json" not in text
    assert "cause_catalog_json" not in text
    assert "group_json=" not in text
    assert len(rendered.read_bytes()) <= 8192


def test_renderer_keeps_all_realistic_root_cause_groups_under_api_limit(
    tmp_path: Path,
) -> None:
    output = _produce(tmp_path, count=40, distinct=True)
    rendered = output / "api-summary.txt"
    text = _render(output, rendered)
    assert "failure_signature_group_count=40" in text
    assert "shown_signature_group_count=40" in text
    assert "omitted_signature_group_count=0" in text
    assert text.count("signature_group_json=") == 40
    assert len(rendered.read_bytes()) <= 8192


def test_fallback_summary_is_bounded_and_points_to_artifact(tmp_path: Path) -> None:
    output = _produce(tmp_path, stage="compile")
    rendered = output / "api-summary.txt"
    result = subprocess.run(
        [sys.executable, str(RENDERER), "--input", str(output / "diagnostics.json"), "--output", str(rendered)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    text = rendered.read_text(encoding="utf-8")
    assert "stage=compile" in text
    assert "LOG_EXCERPT_BEGIN" in text
    assert "SyntaxError: invalid syntax" in text
    assert "full_failure_details=artifact:failure-details.txt" in text


def test_ci_contract_uses_one_artifact_and_one_complete_human_relay() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "python -m pytest -q -ra" in workflow
    assert "Tee-Object" not in workflow
    assert workflow.count("actions/upload-artifact@v6") == 2
    assert workflow.count("actions/download-artifact@v8") == 1
    assert "actions/download-artifact@v6" not in workflow
    assert "name: Python failure diagnostics" in workflow
    assert "api-summary.txt" in workflow
    assert "--max-bytes 8192" in workflow
    assert "INVENTORY_LOG_TAIL_BEGIN" not in workflow
    assert "COMPILE_LOG_TAIL_BEGIN" not in workflow
    assert "failed_stage=inventory" not in workflow
    assert "problem_count:" not in workflow
    assert "first_failure:" not in workflow
    assert "gh api" not in workflow
    assert "matrix:" not in workflow
