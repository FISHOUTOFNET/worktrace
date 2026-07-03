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


def _override_policy() -> dict:
    policy = _policy()
    policy["thresholds"]["file_ordinary_comment_ratio_max"] = 0.12
    policy["thresholds"]["max_contiguous_ordinary_comment_block"] = 4
    policy["thresholds"]["max_inline_comments_per_file"] = 6
    policy["override_max_ratio"] = 0.18
    policy["override_allowed_categories"] = [
        "privacy/security boundary",
        "non-obvious regression test intent",
    ]
    policy["path_threshold_overrides"] = []
    return policy


def test_default_file_ratio_threshold_applies(hygiene, tmp_path):
    policy = _override_policy()
    _write(tmp_path, "src/example.py", "# a\n# b\n# c\n# d\n# e\n# f\n# g\nvalue = 1\n")
    report = hygiene.scan_repository(tmp_path, policy)
    file_report = report["files"][0]
    assert file_report["threshold_source"] == "default"
    assert file_report["applied_ratio_threshold"] == 0.12
    assert "file_comment_ratio" in {v["kind"] for v in file_report["violations"]}


def test_per_path_override_lowers_effective_threshold(hygiene, tmp_path):
    policy = _override_policy()
    policy["path_threshold_overrides"] = [
        {
            "path": "src/example.py",
            "file_ordinary_comment_ratio_max": 0.18,
            "reason": "non-obvious regression test intent",
            "category": "non-obvious regression test intent",
        }
    ]
    content = "# a\n# b\n# c\n" + "\n".join(f"v{i} = {i}" for i in range(17)) + "\n"
    _write(tmp_path, "src/example.py", content)
    report = hygiene.scan_repository(tmp_path, policy)
    file_report = report["files"][0]
    assert file_report["threshold_source"] == "override:src/example.py"
    assert file_report["applied_ratio_threshold"] == 0.18
    assert file_report["ordinary_comment_ratio"] > 0.12
    assert "file_comment_ratio" not in {v["kind"] for v in file_report["violations"]}


def test_override_does_not_affect_other_files(hygiene, tmp_path):
    policy = _override_policy()
    policy["path_threshold_overrides"] = [
        {
            "path": "src/overridden.py",
            "file_ordinary_comment_ratio_max": 0.18,
            "reason": "non-obvious regression test intent",
            "category": "non-obvious regression test intent",
        }
    ]
    content = "# a\n# b\n# c\n" + "\n".join(f"v{i} = {i}" for i in range(17)) + "\n"
    _write(tmp_path, "src/overridden.py", content)
    _write(tmp_path, "src/normal.py", content)
    report = hygiene.scan_repository(tmp_path, policy)
    by_path = {f["path"]: f for f in report["files"]}
    assert by_path["src/overridden.py"]["threshold_source"] == "override:src/overridden.py"
    assert by_path["src/normal.py"]["threshold_source"] == "default"
    assert "file_comment_ratio" in {
        v["kind"] for v in by_path["src/normal.py"]["violations"]
    }


def test_directory_prefix_override_matches(hygiene, tmp_path):
    policy = _override_policy()
    policy["path_threshold_overrides"] = [
        {
            "path": "src/security/",
            "file_ordinary_comment_ratio_max": 0.18,
            "reason": "privacy/security boundary",
            "category": "privacy/security boundary",
        }
    ]
    content = "# a\n# b\n# c\n" + "\n".join(f"v{i} = {i}" for i in range(17)) + "\n"
    _write(tmp_path, "src/security/key.py", content)
    _write(tmp_path, "src/other.py", content)
    report = hygiene.scan_repository(tmp_path, policy)
    by_path = {f["path"]: f for f in report["files"]}
    assert by_path["src/security/key.py"]["threshold_source"] == "override:src/security/"
    assert by_path["src/other.py"]["threshold_source"] == "default"


def test_override_ratio_exceeding_max_is_config_violation(hygiene, tmp_path):
    policy = _override_policy()
    policy["path_threshold_overrides"] = [
        {
            "path": "src/example.py",
            "file_ordinary_comment_ratio_max": 0.25,
            "reason": "non-obvious regression test intent",
            "category": "non-obvious regression test intent",
        }
    ]
    _write(tmp_path, "src/example.py", "value = 1\n")
    report = hygiene.scan_repository(tmp_path, policy)
    kinds = {v["kind"] for v in report["violations"]}
    assert "override_config" in kinds


def test_override_missing_reason_is_config_violation(hygiene, tmp_path):
    policy = _override_policy()
    policy["path_threshold_overrides"] = [
        {
            "path": "src/example.py",
            "file_ordinary_comment_ratio_max": 0.18,
            "category": "non-obvious regression test intent",
        }
    ]
    _write(tmp_path, "src/example.py", "value = 1\n")
    report = hygiene.scan_repository(tmp_path, policy)
    assert "override_config" in {v["kind"] for v in report["violations"]}


def test_override_glob_wildcard_is_config_violation(hygiene, tmp_path):
    policy = _override_policy()
    policy["path_threshold_overrides"] = [
        {
            "path": "src/*.py",
            "file_ordinary_comment_ratio_max": 0.18,
            "reason": "non-obvious regression test intent",
            "category": "non-obvious regression test intent",
        }
    ]
    _write(tmp_path, "src/example.py", "value = 1\n")
    report = hygiene.scan_repository(tmp_path, policy)
    assert "override_config" in {v["kind"] for v in report["violations"]}


def test_repo_ratio_still_counted_across_whole_repo(hygiene, tmp_path):
    policy = _override_policy()
    policy["thresholds"]["repo_ordinary_comment_ratio_max"] = 0.05
    _write(
        tmp_path,
        "src/example.py",
        "# a\n# b\n# c\n# d\n# e\n# f\n# g\n# h\nvalue = 1\n",
    )
    report = hygiene.scan_repository(tmp_path, policy)
    kinds = {v["kind"] for v in report["violations"]}
    assert "repo_comment_ratio" in kinds


def test_contiguous_block_boundary_at_four_passes(hygiene, tmp_path):
    policy = _override_policy()
    _write(tmp_path, "src/example.py", "# a\n# b\n# c\n# d\nvalue = 1\n")
    report = hygiene.scan_repository(tmp_path, policy)
    assert "long_comment_block" not in {v["kind"] for v in report["violations"]}


def test_contiguous_block_boundary_at_five_fails(hygiene, tmp_path):
    policy = _override_policy()
    _write(tmp_path, "src/example.py", "# a\n# b\n# c\n# d\n# e\nvalue = 1\n")
    report = hygiene.scan_repository(tmp_path, policy)
    assert "long_comment_block" in {v["kind"] for v in report["violations"]}


def test_inline_comment_boundary_at_six_passes(hygiene, tmp_path):
    policy = _override_policy()
    lines = [f"value_{i} = {i}  # note {i}" for i in range(6)]
    _write(tmp_path, "src/example.py", "\n".join(lines) + "\n")
    report = hygiene.scan_repository(tmp_path, policy)
    assert "too_many_inline_comments" not in {
        v["kind"] for v in report["violations"]
    }


def test_inline_comment_boundary_at_seven_fails(hygiene, tmp_path):
    policy = _override_policy()
    lines = [f"value_{i} = {i}  # note {i}" for i in range(7)]
    _write(tmp_path, "src/example.py", "\n".join(lines) + "\n")
    report = hygiene.scan_repository(tmp_path, policy)
    assert "too_many_inline_comments" in {
        v["kind"] for v in report["violations"]
    }
