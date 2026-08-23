"""Stable CI workflow boundaries.

These tests intentionally cover only durable orchestration invariants. Detailed
workflow step ordering, benchmark implementation details, artifact names, and
threshold plumbing belong to the scripts/workflows that own them rather than a
large YAML-text mirror in pytest.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.contract, pytest.mark.parallel_safe]

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"


def _source(name: str) -> str:
    return (WORKFLOWS / name).read_text(encoding="utf-8")


def _trigger_block(source: str) -> str:
    return source.split("permissions:", 1)[0]


def test_standard_ci_runs_the_full_non_benchmark_python_suite() -> None:
    source = _source("ci.yml")
    assert "name: Standard validation / Python 3.11 full suite" in source
    assert "scripts/run_pytest_ci.py" in source
    assert '-m "not benchmark"' in source


def test_only_three_long_lived_workflows_exist() -> None:
    workflows = {
        path.name
        for path in WORKFLOWS.iterdir()
        if path.suffix in {".yml", ".yaml"}
    }
    assert workflows == {
        "ci.yml",
        "installer-validation.yml",
        "performance-validation.yml",
    }


def test_performance_validation_is_opt_in_or_scheduled() -> None:
    source = _source("performance-validation.yml")
    triggers = _trigger_block(source)

    assert "workflow_dispatch:" in triggers
    assert "schedule:" in triggers
    assert "pull_request:" in triggers
    assert "types: [labeled]" in triggers
    assert "\n  push:" not in triggers
    assert "run-performance-validation" in source


@pytest.mark.parametrize(
    ("workflow", "group_prefix"),
    [
        ("performance-validation.yml", "performance-validation-"),
        ("installer-validation.yml", "installer-validation-"),
    ],
)
def test_expensive_workflows_cancel_duplicate_runs(
    workflow: str,
    group_prefix: str,
) -> None:
    source = _source(workflow)
    assert "concurrency:" in source
    assert f"group: {group_prefix}" in source
    assert "cancel-in-progress: true" in source


def test_installer_runtime_lifecycle_stays_out_of_standard_ci() -> None:
    standard = _source("ci.yml")
    installer = _source("installer-validation.yml")

    assert "./.github/actions/build-windows-package" in standard
    assert "installer_runtime_smoke.ps1" not in standard
    assert "installer_runtime_smoke.ps1" in installer


@pytest.mark.parametrize(
    "workflow",
    [
        "ci.yml",
        "installer-validation.yml",
        "performance-validation.yml",
    ],
)
def test_validation_checkouts_do_not_persist_credentials(workflow: str) -> None:
    assert "persist-credentials: false" in _source(workflow)
