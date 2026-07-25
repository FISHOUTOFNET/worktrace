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
TIMING_SUMMARY = ROOT / "scripts" / "pytest_timing_summary.py"
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
import threading


def test_passes():
    threading.Event().wait(0.12)


def test_fails():
    threading.Event().wait(0.12)
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


def test_pytest_runner_throttles_progress_writes_for_large_suites(tmp_path: Path) -> None:
    """A large fast suite must not produce ~2 writes per test.

    Without throttling, ``run_pytest_ci.py`` wrote the progress JSON on every
    ``logstart`` and ``logfinish`` hook, producing roughly 2 * <test count>
    Windows file writes (≈5000 for a 2500-test suite). Throttling caps writes
    to one per 25 completed items plus one per elapsed second, plus forced
    writes on collection done and session finish.

    This contract runs ~60 trivial tests and asserts the write count stays
    well below the unthrottled baseline of 2 * 60 = 120 writes. The synthetic
    suite is fast enough that the 1-second time threshold never fires, so the
    write count is dominated by the 25-item interval and the forced writes.
    """
    test_count = 60
    synthetic = tmp_path / "test_synthetic_throttle.py"
    body = "\n".join(
        f"def test_pass_{index:02d}():\n    pass\n" for index in range(test_count)
    )
    synthetic.write_text(body, encoding="utf-8")

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
            "60",  # Long heartbeat so the runner loop does not poll the file often.
            "--",
            "-q",
            "--tb=short",
            "--color=no",
            "-p",
            "no:cacheprovider",
            str(synthetic),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        env={**__import__("os").environ, "WORKTRACE_PYTEST_PROGRESS_FORCE_WRITE": ""},
    )

    assert result.returncode == 0, result.stdout + "\n" + result.stderr

    payload = json.loads(progress.read_text(encoding="utf-8"))
    assert payload["status"] == "finished"
    assert payload["completed"] == test_count
    assert payload["total"] == test_count
    assert "write_count" in payload, "progress payload must expose write_count for observability"

    write_count = int(payload["write_count"])
    # Unthrottled baseline: 2 writes per test (logstart + logfinish) plus 2
    # forced writes (collection + sessionfinish) = 122. Throttled actual:
    # 2 forced writes + up to ceil(60/25) = 3 item-triggered writes = 5. We
    # allow headroom for one or two time-triggered writes on a slow runner.
    unthrottled_baseline = 2 * test_count + 2
    throttled_upper_bound = 15
    assert write_count <= throttled_upper_bound, (
        f"Progress writes not throttled: write_count={write_count} for "
        f"{test_count} tests (unthrottled baseline={unthrottled_baseline}, "
        f"expected bound={throttled_upper_bound})"
    )
    # Sanity: the throttled count must be meaningfully lower than unthrottled.
    assert write_count < unthrottled_baseline / 2


def test_ci_contract_is_artifact_only_with_bounded_progress() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    producer = PRODUCER.read_text(encoding="utf-8")

    assert "# Business-test diagnostics are artifact-only." in workflow
    assert "scripts/run_pytest_ci.py" in workflow
    assert "--heartbeat-seconds 60" in workflow
    assert '*> "test-results/pytest.log"' not in workflow
    assert 'Get-Content -LiteralPath "test-results/pytest.log"' not in workflow

    # Three upload-artifact steps are expected:
    #   1. validation-diagnostics (failure-only, 3-day retention)
    #   2. pytest-timing-summary  (success-only, 1-day retention, ignore-missing)
    #   3. worktrace-windows-smoke (release tags only, 1-day retention)
    assert workflow.count("actions/upload-artifact@v6") == 3
    assert "pytest-timing-summary-${{ inputs.revision }}" in workflow
    assert "if-no-files-found: ignore" in workflow
    assert "name: Generate pytest timing summary" in workflow
    assert "name: Upload pytest timing summary" in workflow
    assert "continue-on-error: true" in workflow
    assert "scripts/pytest_timing_summary.py" in workflow
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


def _write_timing_junit(path: Path) -> None:
    """Write a small JUnit XML with known test times for timing-summary tests."""
    suite = ET.Element(
        "testsuite",
        tests="3",
        failures="0",
        errors="0",
        skipped="0",
        time="2.50",
    )
    cases = [
        ("tests.test_alpha", "test_slow", 1.20),
        ("tests.test_alpha", "test_fast", 0.10),
        ("tests.test_beta", "test_medium", 0.50),
    ]
    for classname, name, seconds in cases:
        ET.SubElement(
            suite,
            "testcase",
            classname=classname,
            name=name,
            time=str(seconds),
        )
    ET.ElementTree(suite).write(path, encoding="utf-8", xml_declaration=True)


def _write_timing_log(path: Path) -> None:
    """Write a synthetic pytest log with a --durations section."""
    path.write_text(
        """
============================= test session starts =============================
collected 3 items

tests/test_alpha.py ..
tests/test_beta.py .

========================= slowest 10 durations ==========================
1.20s call     tests/test_alpha.py::test_slow
0.50s call     tests/test_beta.py::test_medium
0.10s call     tests/test_alpha.py::test_fast
0.05s setup    tests/test_alpha.py::test_slow
0.02s teardown tests/test_alpha.py::test_slow
============================== 3 slowest durations =============================
============================= 3 passed in 2.50s ==============================
""".strip()
        + "\n",
        encoding="utf-8",
    )


def test_timing_summary_produces_structured_json(tmp_path: Path) -> None:
    """The timing summary script must produce the schema-conformant JSON."""
    junit = tmp_path / "pytest-junit.xml"
    log = tmp_path / "pytest.log"
    output = tmp_path / "timing-summary.json"
    _write_timing_junit(junit)
    _write_timing_log(log)

    result = subprocess.run(
        [
            sys.executable,
            str(TIMING_SUMMARY),
            "--junit",
            str(junit),
            "--log",
            str(log),
            "--output",
            str(output),
            "--revision",
            "abc123",
            "--runner",
            "windows-latest",
            "--python-version",
            "3.11",
            "--suite",
            "standard",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "timing_summary_status=ready" in result.stdout
    assert "suite=standard" in result.stdout

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert payload["revision"] == "abc123"
    assert payload["runner"] == "windows-latest"
    assert payload["python_version"] == "3.11"
    assert payload["suite"] == "standard"
    assert payload["test_count"] == 3
    assert payload["pytest_elapsed_seconds"] == 2.5
    # top_tests sorted descending; the slowest test must be first.
    assert payload["top_tests"][0]["test_id"] == "tests.test_alpha::test_slow"
    assert payload["top_tests"][0]["time_seconds"] == 1.2
    # top_files aggregates by file root.
    assert any(entry["file"] == "tests.test_alpha" for entry in payload["top_files"])
    # setup/call/teardown parsed from --durations output.
    assert payload["setup_seconds"] is not None
    assert payload["call_seconds"] is not None
    assert payload["teardown_seconds"] is not None
    # setup = 0.05, call = 1.20 + 0.50 + 0.10 = 1.80, teardown = 0.02
    assert payload["setup_seconds"] == 0.05
    assert payload["call_seconds"] == 1.80
    assert payload["teardown_seconds"] == 0.02


def test_timing_summary_never_masks_test_result_on_missing_inputs(tmp_path: Path) -> None:
    """Missing inputs must not fail the script: it returns 0 and prints fallback."""
    output = tmp_path / "timing-summary.json"
    result = subprocess.run(
        [
            sys.executable,
            str(TIMING_SUMMARY),
            "--junit",
            str(tmp_path / "missing-junit.xml"),
            "--log",
            str(tmp_path / "missing-log.txt"),
            "--output",
            str(output),
            "--revision",
            "abc123",
            "--runner",
            "windows-latest",
            "--python-version",
            "3.11",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    # Output file may or may not be created; the script must not crash.
    # Either a ready status (with zeros) or a fallback status is acceptable.
    assert "timing_summary_status=" in result.stdout
