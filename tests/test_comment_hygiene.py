"""Tests for the WorkTrace comment hygiene gate."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
HYGIENE_PATH = REPO_ROOT / "scripts" / "comment_hygiene.py"
MODULE_NAME = "comment_hygiene"


@pytest.fixture(scope="module")
def hygiene():
    spec = importlib.util.spec_from_file_location(MODULE_NAME, HYGIENE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[MODULE_NAME] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(MODULE_NAME, None)
        raise
    return module


def _policy() -> dict:
    return {
        "version": 1,
        "scan": {
            "include_paths": ["src"],
            "include_extensions": [".py", ".js", ".css", ".html", ".ps1"],
            "exclude_paths": [".git", "__pycache__"],
        },
        "thresholds": {
            "repo_ordinary_comment_ratio_max": 1.0,
            "file_ordinary_comment_ratio_max": 1.0,
            "max_contiguous_ordinary_comment_block": 2,
            "max_inline_comments_per_file": 12,
            "max_docstring_lines_default": 3,
            "max_module_docstring_lines": 4,
        },
        "stale_markers": {
            "fail_patterns": [
                r"\b" + "Ph" + r"ase\s+[0-9A-Za-z.]+\b",
                "migration " + "phase",
                "old behavior",
                "临时兼容",
            ],
            "todo_patterns": [r"\bTODO\b", r"\bFIXME\b", r"\bXXX\b"],
        },
    }


def _write(tmp_path: Path, relative: str, text: str) -> Path:
    path = tmp_path / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _scan(hygiene, tmp_path: Path) -> dict:
    return hygiene.scan_repository(tmp_path, _policy())


def _kinds(report: dict) -> set[str]:
    return {violation["kind"] for violation in report["violations"]}


def test_python_hash_comment_counts_as_ordinary_comment(hygiene, tmp_path):
    _write(tmp_path, "src/example.py", "value = 1\n# current invariant\n")
    report = _scan(hygiene, tmp_path)
    file_report = report["files"][0]
    assert file_report["ordinary_comment_lines"] == 1
    assert file_report["code_lines"] == 1
    assert file_report["ordinary_comment_ratio"] == 0.5


def test_python_docstring_is_not_ordinary_comment(hygiene, tmp_path):
    _write(tmp_path, "src/example.py", '"""Public contract."""\nvalue = 1\n')
    report = _scan(hygiene, tmp_path)
    file_report = report["files"][0]
    assert file_report["docstring_lines"] == 1
    assert file_report["ordinary_comment_lines"] == 0
    assert file_report["code_lines"] == 1


def test_blank_lines_do_not_count_in_ratio(hygiene, tmp_path):
    _write(tmp_path, "src/example.py", "value = 1\n\n# current invariant\n\n")
    report = _scan(hygiene, tmp_path)
    file_report = report["files"][0]
    assert file_report["empty_lines"] == 2
    assert file_report["ordinary_comment_ratio"] == 0.5


def test_stale_marker_is_reported(hygiene, tmp_path):
    marker = "Ph" + "ase 5I"
    _write(tmp_path, "src/example.py", f"# {marker} moved this behavior\nvalue = 1\n")
    assert "stale_marker" in _kinds(_scan(hygiene, tmp_path))


@pytest.mark.parametrize("marker", ["TODO", "FIXME"])
def test_todo_markers_are_reported(hygiene, tmp_path, marker):
    _write(tmp_path, "src/example.py", f"# {marker}: wire this later\nvalue = 1\n")
    assert "todo_marker" in _kinds(_scan(hygiene, tmp_path))


def test_long_contiguous_comment_block_is_reported(hygiene, tmp_path):
    _write(
        tmp_path,
        "src/example.py",
        "# one\n# two\n# three\nvalue = 1\n",
    )
    assert "long_comment_block" in _kinds(_scan(hygiene, tmp_path))


def test_commented_out_code_is_reported(hygiene, tmp_path):
    _write(tmp_path, "src/example.py", "# def disabled():\nvalue = 1\n")
    assert "commented_out_code" in _kinds(_scan(hygiene, tmp_path))


def test_temporary_current_behavior_text_is_not_stale(hygiene, tmp_path):
    _write(
        tmp_path,
        "src/example.py",
        "# temporary resource for display purposes only\nvalue = 1\n",
    )
    assert "stale_marker" not in _kinds(_scan(hygiene, tmp_path))


def test_comment_hygiene_check_passes_for_repository():
    result = subprocess.run(
        [sys.executable, "scripts/comment_hygiene.py", "--check"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
