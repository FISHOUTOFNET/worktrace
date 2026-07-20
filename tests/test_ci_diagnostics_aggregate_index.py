from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.contract, pytest.mark.parallel_safe]

ROOT = Path(__file__).resolve().parents[1]
RENDERER = ROOT / "scripts" / "render_ci_api_summary.py"


def test_chunked_transport_exposes_every_root_cause_in_bounded_lines(
    tmp_path: Path,
) -> None:
    source_groups = [
        {
            "id": f"group-{index:03d}",
            "kind": "failure",
            "message": f"root cause {index} " + ("message " * 40),
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
        "artifact_name": "validation-diagnostics-chunked-index",
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
    lines = summary.read_text(encoding="utf-8").splitlines()
    chunk_lines = [line for line in lines if line.startswith("cause_chunk_json_")]
    assert len(chunk_lines) == 8
    assert all(len(line.encode("utf-8")) < 1600 for line in chunk_lines)
    records = [
        record
        for line in chunk_lines
        for record in json.loads(line.split("=", 1)[1])
    ]
    assert [entry["i"] for entry in records] == [
        f"group-{index:03d}" for index in range(1, 41)
    ]
    assert all(set(entry) == {"i", "k", "l", "m", "n"} for entry in records)
    assert all(entry["n"] == 1 for entry in records)
    assert all(len(entry["m"]) <= 100 for entry in records)
    assert lines.index("ROOT_CAUSE_TRANSPORT_BEGIN") < lines.index(
        "ROOT_CAUSE_INDEX_BEGIN"
    )
