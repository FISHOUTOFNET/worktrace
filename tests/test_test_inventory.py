"""Tests for the static test inventory governance script."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.parallel_safe]

REPO_ROOT = Path(__file__).resolve().parents[1]
INVENTORY_PATH = REPO_ROOT / "scripts" / "test_inventory.py"
MODULE_NAME = "test_inventory"


@pytest.fixture(scope="module")
def inventory():
    spec = importlib.util.spec_from_file_location(MODULE_NAME, INVENTORY_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[MODULE_NAME] = module
    spec.loader.exec_module(module)
    return module


def _write_required_pytest_ini(root: Path, inventory) -> None:
    marker_lines = "\n".join(
        f"    {name}: {description}"
        for name, description in inventory.REQUIRED_MARKERS.items()
    )
    (root / "pytest.ini").write_text(
        "[pytest]\nmarkers =\n" + marker_lines + "\n",
        encoding="utf-8",
    )


def _make_repo(tmp_path: Path, inventory) -> Path:
    root = tmp_path / "repo"
    tests = root / "tests"
    tests.mkdir(parents=True)
    _write_required_pytest_ini(root, inventory)
    (tests / "test_sample.py").write_text(
        "\n".join(
            [
                "import pytest",
                "",
                "pytestmark = [pytest.mark.unit, pytest.mark.parallel_safe]",
                "",
                "def test_one():",
                "    assert True",
                "",
                "@pytest.mark.db",
                "def test_two(temp_db):",
                "    assert temp_db",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return root


def test_inventory_plain_json_and_markdown_outputs(inventory, tmp_path, capsys):
    root = _make_repo(tmp_path, inventory)

    assert inventory.main(["--repo-root", str(root)]) == 0
    plain = capsys.readouterr().out
    assert "WorkTrace Test Inventory" in plain
    assert "Test files: 1" in plain
    assert "Estimated tests: 2" in plain

    assert inventory.main(["--repo-root", str(root), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["test_files"] == 1
    assert payload["estimated_tests"] == 2
    assert payload["markers"]["unit"]["tests"] == 2
    assert payload["markers"]["db"]["tests"] == 1

    assert inventory.main(["--repo-root", str(root), "--markdown"]) == 0
    markdown = capsys.readouterr().out
    assert "# WorkTrace Test Inventory" in markdown
    assert "| `unit` |" in markdown


def test_check_allows_unmarked_tests_as_warning(inventory, tmp_path, capsys):
    root = tmp_path / "repo"
    tests = root / "tests"
    tests.mkdir(parents=True)
    _write_required_pytest_ini(root, inventory)
    (tests / "test_unmarked.py").write_text(
        "def test_unmarked():\n    assert True\n",
        encoding="utf-8",
    )

    assert inventory.main(["--repo-root", str(root), "--check"]) == 0
    out = capsys.readouterr().out
    assert "Inventory check errors: none" in out
    assert "estimated tests are unmarked" in out


def test_check_detects_unregistered_marker(inventory, tmp_path, capsys):
    root = _make_repo(tmp_path, inventory)
    (root / "tests" / "test_unknown_marker.py").write_text(
        "import pytest\n\n@pytest.mark.not_registered\ndef test_bad():\n    assert True\n",
        encoding="utf-8",
    )

    assert inventory.main(["--repo-root", str(root), "--check"]) == 1
    out = capsys.readouterr().out
    assert "test uses unregistered pytest marker: not_registered" in out


def test_check_detects_missing_marker_registration(inventory, tmp_path, capsys):
    root = _make_repo(tmp_path, inventory)
    (root / "pytest.ini").write_text(
        "[pytest]\nmarkers =\n    unit: Only one marker.\n",
        encoding="utf-8",
    )

    assert inventory.main(["--repo-root", str(root), "--check"]) == 1
    out = capsys.readouterr().out
    assert "pytest marker not registered: db" in out


def test_check_detects_webview_conftest(inventory, tmp_path, capsys):
    root = _make_repo(tmp_path, inventory)
    webview = root / "tests" / "webview"
    webview.mkdir()
    (webview / "conftest.py").write_text("# forbidden\n", encoding="utf-8")
    (webview / "test_static.py").write_text(
        "import pytest\npytestmark = pytest.mark.webview_static\n\ndef test_ok():\n    assert True\n",
        encoding="utf-8",
    )

    assert inventory.main(["--repo-root", str(root), "--check"]) == 1
    out = capsys.readouterr().out
    assert "tests/webview/conftest.py must not exist" in out


def test_check_detects_db_signal_without_db_marker(inventory, tmp_path, capsys):
    root = tmp_path / "repo"
    tests = root / "tests"
    tests.mkdir(parents=True)
    _write_required_pytest_ini(root, inventory)
    (root / "test_policy.json").write_text(
        json.dumps(
            {
                "risk_signals": {
                    "db": {
                        "patterns": ["temp_db"],
                        "required_any_markers": ["db"],
                    }
                },
                "risk_marker_overrides": [],
                "budgets": {
                    "max_lines_per_test_file": 100,
                    "max_test_functions_per_test_file": 10,
                    "overrides": [],
                },
                "owners": [],
            }
        ),
        encoding="utf-8",
    )
    (tests / "test_dbish.py").write_text(
        "def test_uses_db(temp_db):\n    assert temp_db\n",
        encoding="utf-8",
    )

    assert inventory.main(["--repo-root", str(root), "--check"]) == 1
    out = capsys.readouterr().out
    assert "risk signal `db` requires one of markers db" in out


def test_check_detects_budget_without_reason_override(inventory, tmp_path, capsys):
    root = _make_repo(tmp_path, inventory)
    (root / "test_policy.json").write_text(
        json.dumps(
            {
                "risk_signals": {},
                "risk_marker_overrides": [],
                "budgets": {
                    "max_lines_per_test_file": 4,
                    "max_test_functions_per_test_file": 10,
                    "overrides": [],
                },
                "owners": [],
            }
        ),
        encoding="utf-8",
    )

    assert inventory.main(["--repo-root", str(root), "--check"]) == 1
    out = capsys.readouterr().out
    assert "test file exceeds budget" in out
