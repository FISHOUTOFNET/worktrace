from __future__ import annotations

import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

pytestmark = [pytest.mark.contract, pytest.mark.integration]

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "pytest_log_to_junit.py"


def test_recovers_partial_results_and_timeout_stack(tmp_path: Path) -> None:
    log = tmp_path / "pytest.log"
    output = tmp_path / "pytest-junit.xml"
    log.write_text(
        "\n".join(
            (
                "tests/test_alpha.py::test_ok PASSED [ 10%]",
                "tests/test_beta.py::test_failed FAILED [ 20%]",
                "tests/test_gamma.py::test_waits +++++++++++++++++ Timeout +++++++++++++++++",
                "~~~~~~~~~~~~~~~~ Stack of MainThread ~~~~~~~~~~~~~~~~",
                '  File "worktrace/collector/collector.py", line 659, in _wait_for_poll_delay',
                "    stop_event.wait(timeout_seconds)",
                "+++++++++++++++++++++++++++++++++++ Timeout +++++++++++++++++++++++++++++++++++",
            )
        )
        + "\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--log",
            str(log),
            "--output",
            str(output),
            "--timeout-seconds",
            "90",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    root = ET.parse(output).getroot()
    assert root.attrib == {
        "name": "pytest-log-recovery",
        "tests": "3",
        "failures": "1",
        "errors": "1",
        "skipped": "0",
    }
    cases = {
        (case.attrib["classname"], case.attrib["name"]): case
        for case in root.findall("testcase")
    }
    failed = cases[("tests.test_beta", "test_failed")].find("failure")
    assert failed is not None
    timeout = cases[("tests.test_gamma", "test_waits")].find("error")
    assert timeout is not None
    assert timeout.attrib["message"] == "pytest-timeout: test exceeded 90 seconds"
    assert "collector.py" in (timeout.text or "")


def test_rejects_log_without_test_progress(tmp_path: Path) -> None:
    log = tmp_path / "pytest.log"
    output = tmp_path / "pytest-junit.xml"
    log.write_text("pytest did not start\n", encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--log", str(log), "--output", str(output)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "no recoverable test results" in result.stderr
    assert not output.exists()
