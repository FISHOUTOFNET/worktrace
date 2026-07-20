from __future__ import annotations

import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.contract, pytest.mark.parallel_safe]

ROOT = Path(__file__).resolve().parents[1]
PRODUCER = ROOT / "scripts" / "pytest_diagnostics.py"
RENDERER = ROOT / "scripts" / "render_ci_api_summary.py"


def _write_junit(path: Path, failures: list[tuple[str, str, str]]) -> None:
    suite = ET.Element("testsuite", tests=str(len(failures)), errors=str(len(failures)))
    for index, (message, location, details) in enumerate(failures, start=1):
        case = ET.SubElement(
            suite,
            "testcase",
            classname="tests.collection",
            name=f"test_collection_{index}",
        )
        error = ET.SubElement(case, "error", message=message)
        error.text = f"{location}: in <module>\n{details}"
    ET.ElementTree(suite).write(path, encoding="utf-8", xml_declaration=True)


def _produce(tmp_path: Path, failures: list[tuple[str, str, str]]) -> Path:
    junit = tmp_path / "pytest-junit.xml"
    log = tmp_path / "pytest.log"
    output = tmp_path / "output"
    _write_junit(junit, failures)
    log.write_text("pytest collection failed\n", encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            str(PRODUCER),
            "--stage",
            "pytest",
            "--junit",
            str(junit),
            "--log",
            str(log),
            "--output-dir",
            str(output),
            "--revision",
            "a" * 40,
            "--artifact-name",
            "validation-diagnostics-test",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return output / "diagnostics.json"


def _render(input_path: Path, output_path: Path, *, max_bytes: int = 65536):
    return subprocess.run(
        [
            sys.executable,
            str(RENDERER),
            "--input",
            str(input_path),
            "--output",
            str(output_path),
            "--max-bytes",
            str(max_bytes),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def _groups(rendered: Path) -> list[dict]:
    return [
        json.loads(line.split("=", 1)[1])
        for line in rendered.read_text(encoding="utf-8").splitlines()
        if line.startswith("group_json=")
    ]


def test_single_collection_error_exposes_real_traceback(tmp_path: Path) -> None:
    diagnostics = _produce(
        tmp_path,
        [
            (
                "ImportError: cannot import name RuntimeStartResult",
                "worktrace/api/app_api.py:7",
                "ImportError: cannot import name RuntimeStartResult from partially initialized module",
            )
        ],
    )
    payload = json.loads(diagnostics.read_text(encoding="utf-8"))
    group = payload["root_cause_groups"][0]
    assert "representative_details" in group
    assert "partially initialized module" in group["representative_details"]

    rendered = tmp_path / "api-summary.txt"
    result = _render(diagnostics, rendered)
    assert result.returncode == 0, result.stderr
    assert "partially initialized module" in rendered.read_text(encoding="utf-8")


def test_multiple_groups_keep_distinct_representative_details(tmp_path: Path) -> None:
    diagnostics = _produce(
        tmp_path,
        [
            ("ImportError: first", "worktrace/api/a.py:1", "FIRST-TRACEBACK"),
            ("AssertionError: second", "worktrace/services/b.py:2", "SECOND-TRACEBACK"),
        ],
    )
    rendered = tmp_path / "api-summary.txt"
    result = _render(diagnostics, rendered)
    assert result.returncode == 0, result.stderr
    groups = _groups(rendered)
    assert len(groups) == 2
    assert "FIRST-TRACEBACK" in " ".join(groups[0]["representative_details"])
    assert "SECOND-TRACEBACK" in " ".join(groups[1]["representative_details"])


def test_non_ascii_traceback_round_trips(tmp_path: Path) -> None:
    diagnostics = _produce(
        tmp_path,
        [("ImportError: 导入失败", "worktrace/api/app_api.py:7", "无法导入：循环依赖")],
    )
    rendered = tmp_path / "api-summary.txt"
    result = _render(diagnostics, rendered)
    assert result.returncode == 0, result.stderr
    text = rendered.read_text(encoding="utf-8")
    assert "导入失败" in text
    assert "循环依赖" in text


def test_renderer_preserves_groups_under_64k_and_truncates_affected_tests_first(
    tmp_path: Path,
) -> None:
    payload = {
        "schema_version": 1,
        "revision": "b" * 40,
        "status": "failed",
        "failed_stage": "pytest",
        "artifact_name": "validation-diagnostics-large",
        "diagnostics_available": True,
        "reason": "",
        "counts": {"total": 500, "passed": 0, "failed": 0, "errors": 500, "skipped": 0},
        "failures": [],
        "log_tail": [],
        "root_cause_groups": [
            {
                "id": "group-001",
                "signature": "error|collection",
                "kind": "error",
                "message": "collection failure",
                "representative_location": "worktrace/api/app_api.py:7",
                "representative_details": "TRACEBACK-DETAIL\n" + ("x" * 1000),
                "affected_tests": [f"tests.synthetic::test_{index:04d}" for index in range(500)],
            },
            {
                "id": "group-002",
                "signature": "error|other",
                "kind": "error",
                "message": "other failure",
                "representative_location": "worktrace/services/a.py:9",
                "representative_details": "SECOND-GROUP-DETAIL",
                "affected_tests": ["tests.synthetic::test_other"],
            },
        ],
    }
    diagnostics = tmp_path / "diagnostics.json"
    diagnostics.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    rendered = tmp_path / "api-summary.txt"
    result = _render(diagnostics, rendered, max_bytes=8192)
    assert result.returncode == 0, result.stderr
    assert len(rendered.read_bytes()) <= 8192
    text = rendered.read_text(encoding="utf-8")
    assert "TRUNCATED=true" in text
    groups = _groups(rendered)
    assert [group["id"] for group in groups] == ["group-001", "group-002"]
    assert groups[0]["affected_test_count"] == 500
    assert groups[0]["omitted_affected_tests"] > 0
    assert "TRACEBACK-DETAIL" in " ".join(groups[0]["representative_details"])


def test_overlong_traceback_is_bounded_without_deleting_group(tmp_path: Path) -> None:
    diagnostics = _produce(
        tmp_path,
        [("ImportError: huge", "worktrace/api/app_api.py:7", "\n".join("line-" + str(i) + "-" + ("x" * 600) for i in range(500)))],
    )
    rendered = tmp_path / "api-summary.txt"
    result = _render(diagnostics, rendered, max_bytes=4096)
    assert result.returncode == 0, result.stderr
    assert len(rendered.read_bytes()) <= 4096
    groups = _groups(rendered)
    assert len(groups) == 1
    assert groups[0]["omitted_detail_lines"] > 0


def test_producer_and_renderer_group_fields_match(tmp_path: Path) -> None:
    diagnostics = _produce(
        tmp_path,
        [("ImportError: contract", "worktrace/runtime/contracts.py:1", "CONTRACT-DETAIL")],
    )
    payload = json.loads(diagnostics.read_text(encoding="utf-8"))
    rendered = tmp_path / "api-summary.txt"
    result = _render(diagnostics, rendered)
    assert result.returncode == 0, result.stderr
    group = _groups(rendered)[0]
    source_group = payload["root_cause_groups"][0]
    assert group["id"] == source_group["id"]
    assert group["kind"] == source_group["kind"]
    assert group["location"] == source_group["representative_location"]
    assert "CONTRACT-DETAIL" in " ".join(group["representative_details"])


def test_missing_diagnostics_fails_closed(tmp_path: Path) -> None:
    result = _render(tmp_path / "missing.json", tmp_path / "output.txt")
    assert result.returncode != 0
    assert not (tmp_path / "output.txt").exists()


def test_malformed_diagnostics_fails_closed(tmp_path: Path) -> None:
    diagnostics = tmp_path / "diagnostics.json"
    diagnostics.write_text(json.dumps({"status": "failed"}), encoding="utf-8")
    result = _render(diagnostics, tmp_path / "output.txt")
    assert result.returncode != 0
    assert "missing fields" in result.stderr
