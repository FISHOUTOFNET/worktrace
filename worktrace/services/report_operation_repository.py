"""Bulk read repository for immutable current-format report operations."""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Any

from .report_projection_model import InvalidInputError
from .report_replay_binding import ReplayBinding


def load_operations_by_date(
    conn,
    start_date: str,
    end_date: str,
) -> dict[str, list[dict[str, Any]]]:
    """Load an operation range and all durable members with two SQL statements."""

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
            payload = json.loads(str(operation.pop("payload_json", "{}")))
        except json.JSONDecodeError as exc:
            raise InvalidInputError("操作负载损坏") from exc
        if not isinstance(payload, dict):
            raise InvalidInputError("操作负载损坏")
        try:
            binding = ReplayBinding(str(payload.pop("replay_binding")))
        except (KeyError, ValueError) as exc:
            raise InvalidInputError("操作重放绑定损坏") from exc
        operation["payload"] = payload
        operation["replay_binding"] = binding.value
        operation["members"] = {
            role: list(values)
            for role, values in members_by_operation[int(operation["id"])].items()
        }
        result[str(operation["report_date"])].append(operation)
    return dict(result)


def load_operations(conn, report_date: str) -> list[dict[str, Any]]:
    return load_operations_by_date(conn, report_date, report_date).get(
        report_date,
        [],
    )


__all__ = ["load_operations", "load_operations_by_date"]
