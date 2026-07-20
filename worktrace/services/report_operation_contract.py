"""Shared current-only contract for report operation payloads and member graph.

The runtime replay engine, the read boundary repository, and the secure
backup validator all delegate to this module so there is exactly one fact
source for:

* the supported operation type set;
* the allowed payload key set per operation type;
* the expected member role set per operation type;
* payload metadata (version + members-only binding) acceptance;
* member identity integrity (non-empty, distinct, well-formed, in-date).

The contract is current-only: the only accepted replay binding is
``ReplayBinding.MEMBERS``. Legacy ``"revision"`` bindings are rejected at
every ingress (repository read boundary, runtime engine payload validation,
secure backup staging validation).
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from .report_projection_model import InvalidInputError, ReportMemberIdentity
from .report_replay_binding import ReplayBinding

OPERATION_PAYLOAD_VERSION = 5

SUPPORTED_OPERATION_TYPES: frozenset[str] = frozenset(
    {
        "edit_session",
        "hide_session",
        "merge_sessions",
        "copy_session",
        "hide_activity",
        "split_session",
    }
)


def expected_roles(operation_type: str) -> set[str] | None:
    """Return the canonical member role set for an operation type.

    Returns ``None`` for unknown operation types so callers can reject them
    explicitly without duplicating the type list.
    """

    if operation_type == "merge_sessions":
        return {"source", "target"}
    if operation_type == "hide_activity":
        return {"source", "affected"}
    if operation_type in {
        "edit_session",
        "hide_session",
        "copy_session",
        "split_session",
    }:
        return {"source"}
    return None


def allowed_payload_keys(operation_type: str) -> set[str] | None:
    """Return the canonical payload key set for an operation type.

    Returns ``None`` for unknown operation types so callers can reject them
    explicitly without duplicating the type list.
    """

    allowed = {"payload_version", "replay_binding"}
    if operation_type == "edit_session":
        return allowed | {"project", "duration", "note"}
    if operation_type == "hide_activity":
        return allowed | {"summary_id"}
    if operation_type in {
        "hide_session",
        "copy_session",
        "merge_sessions",
        "split_session",
    }:
        return allowed
    return None


def validate_operation_type(operation_type: str) -> None:
    """Reject unknown operation types with the canonical error code."""

    if operation_type not in SUPPORTED_OPERATION_TYPES:
        raise InvalidInputError("操作类型损坏")


def validate_payload_metadata(payload: Mapping[str, Any]) -> None:
    """Reject non-current payload version or non-members replay binding."""

    version = payload.get("payload_version")
    if (
        isinstance(version, bool)
        or not isinstance(version, int)
        or version != OPERATION_PAYLOAD_VERSION
    ):
        raise InvalidInputError("操作负载版本损坏")
    binding_value = payload.get("replay_binding")
    try:
        binding = ReplayBinding(str(binding_value))
    except (KeyError, ValueError, TypeError) as exc:
        raise InvalidInputError("操作重放绑定损坏") from exc
    if binding is not ReplayBinding.MEMBERS:
        raise InvalidInputError("操作重放绑定损坏")


def validate_payload_fields(
    operation_type: str,
    payload: Mapping[str, Any],
) -> None:
    """Reject payload fields outside the canonical allow-list for the type."""

    allowed = allowed_payload_keys(operation_type)
    if allowed is None:
        raise InvalidInputError("操作类型损坏")
    unknown = set(payload) - allowed
    if unknown:
        raise InvalidInputError("操作负载字段损坏")


def _identity_tuple(member: ReportMemberIdentity) -> tuple[str, int, str]:
    return (member.report_date, member.activity_id, member.slice_start_time)


def validate_member_graph(
    operation_type: str,
    report_date: str,
    members: Mapping[str, Sequence[ReportMemberIdentity]],
) -> None:
    """Reject malformed member role sets or member identity tuples.

    Caller-specific dispatch (e.g. merge adjacency, split undo chain) is out
    of scope for this contract; only the structural invariants that every
    current-only operation must satisfy live here.
    """

    expected = expected_roles(operation_type)
    if expected is None:
        raise InvalidInputError("操作类型损坏")
    if set(members) != expected:
        raise InvalidInputError("操作成员角色损坏")
    for role in expected:
        identities = list(members.get(role, ()))
        keys = [_identity_tuple(member) for member in identities]
        if not keys or len(keys) != len(set(keys)):
            raise InvalidInputError("操作成员重复或缺失")
        if any(
            date != report_date
            or aid <= 0
            or not start
            for date, aid, start in keys
        ):
            raise InvalidInputError("操作成员标识损坏")
    if operation_type == "hide_activity":
        source = {_identity_tuple(m) for m in members.get("source", ())}
        affected = {_identity_tuple(m) for m in members.get("affected", ())}
        if not affected or not affected.issubset(source):
            raise InvalidInputError("操作成员角色损坏")


__all__ = [
    "OPERATION_PAYLOAD_VERSION",
    "SUPPORTED_OPERATION_TYPES",
    "allowed_payload_keys",
    "expected_roles",
    "validate_member_graph",
    "validate_operation_type",
    "validate_payload_fields",
    "validate_payload_metadata",
]
