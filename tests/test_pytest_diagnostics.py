from __future__ import annotations

import base64
from pathlib import Path

import pytest

from scripts import pytest_diagnostics

pytestmark = [pytest.mark.unit, pytest.mark.contract]


def _problem(index: int) -> pytest_diagnostics.Problem:
    return pytest_diagnostics.Problem(
        test_id=f"tests.test_example::test_case_{index}",
        kind="failure",
        location=f"tests/test_example.py:{index}",
        message=f"assertion {index}",
        details=f"tests/test_example.py:{index}: AssertionError\nassert {index} == 0",
    )


def test_cross_job_report_contains_every_manifest_and_detail_on_single_lines():
    problems = [_problem(1), _problem(2)]
    report = pytest_diagnostics._compact_cross_job_report(10, 1, problems)
    lines = report.splitlines()

    assert lines[0] == pytest_diagnostics.MANIFEST_BEGIN
    assert "Total: 10 | Passed: 7 | Failed: 2 | Errors: 0 | Skipped: 1" in lines
    assert any("tests.test_example::test_case_1 | failure" in line for line in lines)
    assert any("tests.test_example::test_case_2 | failure" in line for line in lines)
    assert lines[-1] == pytest_diagnostics.DETAILS_END
    detail_lines = [line for line in lines if "AssertionError" in line]
    assert len(detail_lines) == 2
    assert all("\n" not in line for line in detail_lines)


def test_github_output_round_trips_complete_cross_job_report(tmp_path, monkeypatch):
    output = tmp_path / "github-output.txt"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    problem = _problem(3)
    report = pytest_diagnostics._compact_cross_job_report(1, 0, [problem])

    pytest_diagnostics._append_github_outputs(
        [problem],
        cross_job_report=report,
    )

    values = dict(
        line.split("=", 1)
        for line in output.read_text(encoding="utf-8").splitlines()
    )
    assert values["problem_count"] == "1"
    assert values["first_failure"] == problem.test_id
    decoded = base64.b64decode(values["diagnostics_b64"]).decode("utf-8")
    assert decoded == report
