from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = [pytest.mark.contract]

_ROOT = Path(__file__).resolve().parents[1]


def _function_source(relative: str, function_name: str) -> str:
    source = (_ROOT / relative).read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == function_name:
            return ast.get_source_segment(source, node) or ""
    raise AssertionError(f"function not found: {relative}:{function_name}")


def test_database_replacement_arms_recovery_before_requesting_hold():
    """Only database replacement pre-arms a cross-restart recovery seal.

    Ordinary read-only snapshots do not replace the database and create no
    irreversible durable effect; they must not arm a recovery seal. Database
    replacement is the only maintenance intent that requires durable recovery
    evidence before requesting the collector hold.
    """

    source = _function_source(
        "worktrace/services/database_maintenance_service.py",
        "_maintain",
    )
    arm = source.index("arm_recovery(reason)")
    hold = source.index("MaintenancePhase.HOLD_REQUESTED")
    assert arm < hold
    # The arm_recovery call must be gated on DATABASE_REPLACEMENT intent.
    gate_segment = source[:arm]
    assert "if intent is MaintenanceIntent.DATABASE_REPLACEMENT" in gate_segment
