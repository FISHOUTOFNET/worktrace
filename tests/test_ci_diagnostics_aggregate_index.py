from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.contract, pytest.mark.parallel_safe]

ROOT = Path(__file__).resolve().parents[1]
RENDERER = ROOT / "scripts" / "render_ci_api_summary.py"


def test_aggregate_index_exposes_every_root_cause_on_one_line(tmp_path: Path) -> None:
    source_groups = [
        {
            "id": f"group-{index:03d}",
            "kind": "failure",
            "message": f"root cause {index}",
            "representative_location": f"tests/test_{index}.py:{index}",
            "representative_details": "TRACEBACK\n" + ("x" * 1200),
            "affected_tests": [f"tests.synthetic::test_{index}"],
        }
        for index in range(1, 41)
    ]
    payload = {
        "schema_version": 1,
        "revision": "d" * 40,
        "status": "failed",
        "failed_stage": "pytest",
        "artifact_name": "validation-diagnostics-aggregate-index",
        "diagnostics_available": True,
        "reason": "",
        "counts": {
            "total": 40,
            "passed": 0,
            "failed": 40,
            "errors": 0,
            "skipped": 0,
        },
        "failures": [],
        "log_tail": [],
        "root_cause_groups": source_groups,
    }
    diagnostics = tmp_path / "diagnostics.json"
    summary = tmp_path / "api-summary.txt"
    diagnostics.write_text(json.dumps(payload), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(RENDERER),
            "--input",
            str(diagnostics),
            "--output",
            str(summary),
            "--max-bytes",
            "65536",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    aggregate_lines = [
        line
        for line in summary.read_text(encoding="utf-8").splitlines()
        if line.startswith("cause_index_json=")
    ]
    assert len(aggregate_lines) == 1
    aggregate = json.loads(aggregate_lines[0].split("=", 1)[1])
    assert [entry["id"] for entry in aggregate] == [
        f"group-{index:03d}" for index in range(1, 41)
    ]
    assert all(
        set(entry)
        == {"id", "kind", "location", "message", "affected_test_count"}
        for entry in aggregate
    )
    assert all(entry["affected_test_count"] == 1 for entry in aggregate)
