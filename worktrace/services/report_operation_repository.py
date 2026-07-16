"""Bulk read repository for immutable report operations."""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Any

from .report_projection_model import InvalidInputError

# Admission revisions protect the initial write. Once an operation has durable
# member identities, replay is bound to those members rather than to mutable
# open/closed duration state. The replay engine already treats a legacy-shaped
# revision plus exact members as member-bound; this adapter preserves the
# original bytes separately for audit while using that stable replay contract.
_MEMBER_BOUND_REPLAY_REVISION = "0" * 40


def load_operations_by_date(
    conn,
    start_date: str,
    end_date: str,
) -> dict[str, list[dict[str, Any]]]:
    """Load an operation range and all members with two SQL statements."""

    operation_rows = conn.execute(
        """
        SELECT *
        FROM report_session_operation
        WHERE report_date BETWEEN ? AND ?
        ORDER BY report_date, sequence, id
        """,
        (start_date, end_date),
    ).fetchall()
    operations = [dict(row) for row in operation_rows]
    if not operations:
        return {}
    operation_ids = [int(row["id"]) for row in operations]
    members_by_operation: dict[int, dict[str, list[dict[str, Any]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for chunk_start in range(0, len(operation_ids), 800):
        chunk = operation_ids[chunk_start : chunk_start + 800]
        placeholders = ",".join("?" for _ in chunk)
        rows = conn.execute(
            f"""
            SELECT operation_id, role, activity_id, report_date,
                   slice_start_time, display_order
            FROM report_session_operation_member
            WHERE operation_id IN ({placeholders})
            ORDER BY operation_id, role, display_order, activity_id
            """,
            chunk,
        ).fetchall()
        for row in rows:
            item = dict(row)
            operation_id = int(item.pop("operation_id"))
            role = str(item.pop("role"))
            item.pop("display_order", None)
            members_by_operation[operation_id][role].append(item)
    result: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for operation in operations:
        try:
            operation["payload"] = json.loads(
                str(operation.pop("payload_json", "{}"))
            )
        except json.JSONDecodeError as exc:
            raise InvalidInputError("操作负载损坏") from exc
        operation["members"] = {
            role: list(values)
            for role, values in members_by_operation[int(operation["id"])].items()
        }
        _bind_replay_to_members(operation)
        result[str(operation["report_date"])].append(operation)
    return dict(result)


def load_operations(conn, report_date: str) -> list[dict[str, Any]]:
    return load_operations_by_date(conn, report_date, report_date).get(
        report_date,
        [],
    )


def _bind_replay_to_members(operation: dict[str, Any]) -> None:
    members = operation.get("members") or {}
    if members.get("source"):
        operation["source_admission_revision"] = operation.get(
            "source_expected_revision"
        )
        operation["source_expected_revision"] = _MEMBER_BOUND_REPLAY_REVISION
    if members.get("target"):
        operation["target_admission_revision"] = operation.get(
            "target_expected_revision"
        )
        operation["target_expected_revision"] = _MEMBER_BOUND_REPLAY_REVISION


__all__ = ["load_operations", "load_operations_by_date"]
