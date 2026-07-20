from __future__ import annotations

import ast
from pathlib import Path

import pytest

from worktrace.services.report_replay_binding import ReplayBinding
from worktrace.services.report_session_operation_engine import OPERATION_PAYLOAD_VERSION

pytestmark = [pytest.mark.unit, pytest.mark.contract, pytest.mark.parallel_safe]
ROOT = Path(__file__).resolve().parents[1]


def test_projection_contract_is_current_only_v5_with_explicit_binding() -> None:
    assert OPERATION_PAYLOAD_VERSION == 5
    assert {binding.value for binding in ReplayBinding} == {"revision", "members"}


def test_projection_repository_rejects_missing_or_non_current_payload_metadata() -> None:
    path = ROOT / "worktrace/services/report_operation_repository.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    source = ast.unparse(tree)

    assert "payload_version != OPERATION_PAYLOAD_VERSION" in source
    assert "ReplayBinding" in source
    assert "操作负载版本损坏" in source
    assert "操作重放绑定损坏" in source
    assert "legacy_projection_revision" not in source
    assert "payload_version == 4" not in source


def test_projection_engine_contains_no_legacy_binding_inference() -> None:
    source = (
        ROOT / "worktrace/services/report_session_operation_engine.py"
    ).read_text(encoding="utf-8")
    assert "legacy_projection_revision" not in source
    assert "payload_version == 4" not in source
    assert "replay_binding or" not in source
