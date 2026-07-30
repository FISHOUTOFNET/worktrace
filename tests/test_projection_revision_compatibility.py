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


def test_projection_contract_is_current_only_v6_with_members_only_binding() -> None:
    """ReplayBinding must accept only the single members-only contract.

    Legacy ``"revision"`` replay bindings are retired from the enum and from
    every ingress (repository read boundary, runtime engine payload validation,
    secure backup staging validation).
    """
    assert OPERATION_PAYLOAD_VERSION == 6
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
    # Repository must not redefine operation-type or field sets locally.
    assert "def _allowed_payload_keys" not in repo_source
    assert '"edit_session"' not in repo_source
    assert '"hide_activity"' not in repo_source

    engine_source = (
        ROOT / "worktrace/services/report_session_operation_engine.py"
    ).read_text(encoding="utf-8")
    assert "from .report_operation_contract import" in engine_source
    # Engine must delegate to contract validators, not re-derive locally.
    assert "validate_operation_type" in engine_source
    assert "validate_payload_metadata" in engine_source
    assert "validate_payload_fields" in engine_source
    assert "validate_member_graph" in engine_source
    # Engine must not redefine role-set or field lookup locally.
    assert "def _expected_roles" not in engine_source
    assert "def _allowed_payload_keys" not in engine_source
    assert "def _members_are_valid" not in engine_source

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
    assert "OPERATION_PAYLOAD_VERSION = 6" not in engine_source
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

    # Repository delegates validation to the shared contract.
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


# --- Projection architecture: builder is the single business owner ---


def test_projection_provider_does_not_import_snapshot_private_symbols() -> None:
    """Provider must NOT import any private symbols from Snapshot service.

    The projection business computation lives in the public Builder module.
    The Provider depends on the Builder, not on the Snapshot service's
    private implementation details.
    """
    provider_source = (
        ROOT / "worktrace/services/report_projection_provider.py"
    ).read_text(encoding="utf-8")
    # Must import from the public builder, not the snapshot service.
    assert "from .report_projection_builder import" in provider_source
    # Must NOT import private symbols from the snapshot service.
    assert "from .report_projection_snapshot_service import _" not in provider_source
    assert (
        "report_projection_snapshot_service._compute_projection"
        not in provider_source
    )
    assert (
        "report_projection_snapshot_service._ProjectionComputation"
        not in provider_source
    )


def test_snapshot_service_does_not_import_provider_private_symbols() -> None:
    """Snapshot service must NOT import any private symbols from Provider.

    The dependency direction is: Provider → Builder, Snapshot → Builder.
    The Snapshot service must not depend on the Provider's internal state.
    """
    snapshot_source = (
        ROOT / "worktrace/services/report_projection_snapshot_service.py"
    ).read_text(encoding="utf-8")
    # Must import from the public builder, not the provider.
    assert "from .report_projection_builder import" in snapshot_source
    # Must NOT import private symbols from the provider.
    assert "from .report_projection_provider import _" not in snapshot_source
    assert "report_projection_provider._" not in snapshot_source


def test_builder_is_the_single_projection_business_owner() -> None:
    """Both materializers must depend on the public Builder, not duplicate logic.

    The Builder module (``report_projection_builder``) is the sole owner of
    projection business computation: fact query, session build, operation
    replay, standalone status, sorting, and content hash. Neither the
    Provider nor the Snapshot service may duplicate these responsibilities.
    """
    builder_source = (
        ROOT / "worktrace/services/report_projection_builder.py"
    ).read_text(encoding="utf-8")
    # Builder must own the computation function and dataclass.
    assert "def compute_projection(" in builder_source
    assert "class ProjectionComputation" in builder_source

    provider_source = (
        ROOT / "worktrace/services/report_projection_provider.py"
    ).read_text(encoding="utf-8")
    # Provider must call the builder's compute_projection.
    assert "compute_projection" in provider_source
    # Provider must NOT redefine the business computation.
    assert "def _compute_projection(" not in provider_source
    assert "class _ProjectionComputation" not in provider_source

    snapshot_source = (
        ROOT / "worktrace/services/report_projection_snapshot_service.py"
    ).read_text(encoding="utf-8")
    # Snapshot service must call the builder's compute_projection.
    assert "compute_projection" in snapshot_source
    # Snapshot service must NOT redefine the business computation.
    assert "def _compute_projection(" not in snapshot_source
    assert "class _ProjectionComputation" not in snapshot_source
