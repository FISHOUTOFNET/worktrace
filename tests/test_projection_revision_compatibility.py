from __future__ import annotations

import ast
from pathlib import Path

import pytest

from worktrace.services.report_operation_contract import (
    OPERATION_PAYLOAD_VERSION,
    SUPPORTED_OPERATION_TYPES,
    allowed_payload_keys,
    expected_roles,
)
from worktrace.services.report_replay_binding import ReplayBinding

pytestmark = [pytest.mark.unit, pytest.mark.contract, pytest.mark.parallel_safe]
ROOT = Path(__file__).resolve().parents[1]


def test_projection_contract_is_current_only_v5_with_members_only_binding() -> None:
    """ReplayBinding must accept only the single members-only contract.

    Legacy ``"revision"`` replay bindings are retired from the enum and from
    every ingress (repository read boundary, runtime engine payload validation,
    secure backup staging validation).
    """
    assert OPERATION_PAYLOAD_VERSION == 5
    assert {binding.value for binding in ReplayBinding} == {"members"}
    assert not hasattr(ReplayBinding, "REVISION")


def test_contract_module_is_the_single_source_for_operation_type_role_and_field_lists() -> None:
    """No second operation-type / role / allowed-field list may exist.

    The repository, runtime engine, and secure backup validator must all
    delegate to ``report_operation_contract`` so the current-only contract
    cannot drift between ingresses.
    """
    contract_source = (
        ROOT / "worktrace/services/report_operation_contract.py"
    ).read_text(encoding="utf-8")
    # Sanity: the contract enumerates the canonical operation-type set once.
    assert "edit_session" in contract_source
    assert "hide_activity" in contract_source
    assert "split_session" in contract_source

    repo_source = (
        ROOT / "worktrace/services/report_operation_repository.py"
    ).read_text(encoding="utf-8")
    assert "from .report_operation_contract import" in repo_source
    assert "validate_payload_metadata" in repo_source
    assert "validate_payload_fields" in repo_source
    assert "validate_operation_type" in repo_source
    # The repository must not redefine the operation-type set or the
    # allowed-field set locally; it must delegate.
    assert "def _allowed_payload_keys" not in repo_source
    assert '"edit_session"' not in repo_source
    assert '"hide_activity"' not in repo_source

    engine_source = (
        ROOT / "worktrace/services/report_session_operation_engine.py"
    ).read_text(encoding="utf-8")
    assert "from .report_operation_contract import" in engine_source
    assert "expected_roles" in engine_source
    assert "allowed_payload_keys" in engine_source
    # The engine must not redefine the role-set locally.
    assert "def _expected_roles" not in engine_source

    backup_source = (
        ROOT / "worktrace/services/secure_backup_validation.py"
    ).read_text(encoding="utf-8")
    assert "from .report_operation_contract import" in backup_source
    assert "validate_payload_metadata" in backup_source
    assert "validate_payload_fields" in backup_source
    assert "validate_operation_type" in backup_source


def test_contract_module_does_not_redefine_payload_version() -> None:
    """The runtime engine must not redefine ``OPERATION_PAYLOAD_VERSION``.

    The contract module is the only source of the constant; the engine
    imports it from the contract so backup validation and the read boundary
    share one truth.
    """
    engine_source = (
        ROOT / "worktrace/services/report_session_operation_engine.py"
    ).read_text(encoding="utf-8")
    assert "OPERATION_PAYLOAD_VERSION = 5" not in engine_source
    assert "from .report_operation_contract import" in engine_source
    assert "OPERATION_PAYLOAD_VERSION" in engine_source


def test_contract_role_and_field_lookups_are_consistent() -> None:
    """Every supported operation type must have a role set and a field set."""
    for operation_type in SUPPORTED_OPERATION_TYPES:
        roles = expected_roles(operation_type)
        fields = allowed_payload_keys(operation_type)
        assert roles is not None
        assert fields is not None
        assert "payload_version" in fields
        assert "replay_binding" in fields
    # Unknown operation types must return None so callers can reject explicitly.
    assert expected_roles("unknown_op") is None
    assert allowed_payload_keys("unknown_op") is None


def test_projection_repository_rejects_missing_or_non_current_payload_metadata() -> None:
    path = ROOT / "worktrace/services/report_operation_repository.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    source = ast.unparse(tree)

    # The repository delegates metadata/binding/field validation to the
    # shared contract; legacy revision replay and old payload versions are
    # rejected by the contract, not by duplicated local checks.
    assert "from .report_operation_contract import" in source
    assert "validate_payload_metadata(payload)" in source
    assert "validate_operation_type(operation_type)" in source
    assert "validate_payload_fields(operation_type, payload)" in source
    assert "legacy_projection_revision" not in source
    assert "payload_version == 4" not in source
    assert '"replay_binding":"revision"' not in source


def test_projection_engine_contains_no_legacy_binding_inference() -> None:
    source = (
        ROOT / "worktrace/services/report_session_operation_engine.py"
    ).read_text(encoding="utf-8")
    assert "legacy_projection_revision" not in source
    assert "payload_version == 4" not in source
    assert "replay_binding or" not in source


def test_projection_engine_contains_no_revision_replay_branch() -> None:
    """The runtime replay engine must not carry any revision-replay branch.

    The current-only contract dispatches by member identity only; the
    retired ``_revision_matches`` helper and every ``ReplayBinding.REVISION``
    branch must be absent from the engine source so legacy bindings cannot
    influence durable replay state.
    """
    source = (
        ROOT / "worktrace/services/report_session_operation_engine.py"
    ).read_text(encoding="utf-8")
    assert "_revision_matches" not in source
    assert "ReplayBinding.REVISION" not in source
    assert "source_revision_conflict" not in source
    assert "target_revision_conflict" not in source


def test_replay_binding_rejects_legacy_revision_value() -> None:
    """The ReplayBinding enum must reject the retired ``"revision"`` value."""
    with pytest.raises(ValueError):
        ReplayBinding("revision")
