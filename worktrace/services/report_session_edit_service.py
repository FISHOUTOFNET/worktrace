"""Timeline edit command supporting persisted-open project/note edits.

Closed-session edits delegate to the canonical mutation UOW. Open sessions use
the same request receipts and operation replay, while the selected project is
also persisted as the activity's manual assignment in the same transaction.
Duration and structural operations remain unavailable while the row is open.
"""

from __future__ import annotations

import sqlite3

from ..constants import STATUS_NORMAL
from ..db import get_connection
from . import assignment_command_service
from . import report_session_operation_service as operations
from .report_projection_identity import stable_json_hash
from .report_projection_model import (
    DatabaseBusyError,
    InvalidInputError,
    MutationResult,
    OperationNotAllowedError,
    RequestIdConflictError,
    RevisionConflictError,
    StaleSelectionError,
)
from .report_session_operation_engine import APPLIED


def edit_session(
    report_date: str,
    projection_instance_key: str,
    expected_projection_revision: str,
    request_id: str,
    *,
    project_id: int | None,
    adjusted_duration_seconds: int | None,
    note: str,
) -> MutationResult:
    if adjusted_duration_seconds is not None:
        with get_connection() as conn:
            from .report_projection_snapshot_service import build_visible_snapshot

            snapshot = build_visible_snapshot(report_date, report_date, conn=conn)
            source = operations._find_entry(
                snapshot.final_sessions, projection_instance_key
            )
        if source is None or bool(source.get("is_in_progress")):
            raise OperationNotAllowedError()
        return operations.edit_session(
            report_date,
            projection_instance_key,
            expected_projection_revision,
            request_id,
            project_id=project_id,
            adjusted_duration_seconds=adjusted_duration_seconds,
            note=note,
        )

    with get_connection() as probe:
        from .report_projection_snapshot_service import build_visible_snapshot

        source = operations._find_entry(
            build_visible_snapshot(report_date, report_date, conn=probe).final_sessions,
            projection_instance_key,
        )
    if source is None:
        raise StaleSelectionError()
    if not bool(source.get("is_in_progress")):
        return operations.edit_session(
            report_date,
            projection_instance_key,
            expected_projection_revision,
            request_id,
            project_id=project_id,
            adjusted_duration_seconds=None,
            note=note,
        )
    return _edit_open_session(
        report_date,
        projection_instance_key,
        expected_projection_revision,
        request_id,
        project_id=project_id,
        note=note,
    )


def _edit_open_session(
    report_date: str,
    source_key: str,
    source_revision: str,
    request_id: str,
    *,
    project_id: int | None,
    note: str,
) -> MutationResult:
    if not request_id or not report_date or not source_key or not source_revision:
        raise InvalidInputError()
    intent = {
        "report_date": report_date,
        "operation_type": "edit_session",
        "source_instance_key": source_key,
        "source_expected_revision": source_revision,
        "target_instance_key": None,
        "target_expected_revision": None,
        "direction": None,
        "payload_input": {
            "project_id": project_id,
            "adjusted_duration_seconds": None,
            "note": note,
        },
    }
    signature = stable_json_hash(intent)
    with get_connection() as conn:
        try:
            conn.execute("BEGIN IMMEDIATE")
            receipt = operations._find_request(conn, request_id)
            if receipt is not None:
                if str(receipt["input_signature"]) != signature:
                    raise RequestIdConflictError()
                result = operations._mutation_result_from_receipt(receipt)
                conn.commit()
                return result

            from .report_projection_snapshot_service import build_visible_snapshot

            before = build_visible_snapshot(report_date, report_date, conn=conn)
            source = operations._find_entry(before.final_sessions, source_key)
            if source is None:
                raise StaleSelectionError()
            if str(source.get("projection_revision") or "") != source_revision:
                raise RevisionConflictError()
            open_activity_id = int(source.get("open_activity_id") or 0)
            if (
                not bool(source.get("is_in_progress"))
                or open_activity_id <= 0
                or str(source.get("status_code") or source.get("status") or "")
                != STATUS_NORMAL
            ):
                raise OperationNotAllowedError()

            if project_id is not None and not assignment_command_service.upsert_assignment(
                conn,
                activity_id=open_activity_id,
                project_id=int(project_id),
                confidence=100,
                source="manual",
                is_manual=True,
            ):
                raise OperationNotAllowedError()

            payload, roles, undo_of = operations._operation_input(
                conn,
                "edit_session",
                source,
                None,
                {
                    "project_id": project_id,
                    "adjusted_duration_seconds": None,
                    "note": note,
                },
            )
            if "duration" in payload:
                raise OperationNotAllowedError()
            if not roles.get("source"):
                slice_start = str(source.get("start_time") or "")
                if not slice_start:
                    raise StaleSelectionError()
                roles["source"] = [
                    {
                        "report_date": report_date,
                        "activity_id": open_activity_id,
                        "slice_start_time": slice_start,
                    }
                ]

            sequence = operations._next_sequence(conn, report_date)
            conn.execute("SAVEPOINT report_operation")
            operation_id = operations._insert_operation(
                conn,
                report_date=report_date,
                sequence=sequence,
                operation_type="edit_session",
                source_instance_key=source_key,
                source_expected_revision=source_revision,
                target_instance_key=None,
                target_expected_revision=None,
                direction=None,
                undo_of_operation_id=undo_of,
                payload=payload,
            )
            operations._insert_members(conn, operation_id, roles)
            after = build_visible_snapshot(report_date, report_date, conn=conn)
            diagnostic = next(
                (
                    item
                    for item in after.operation_diagnostics
                    if item.operation_id == operation_id
                ),
                None,
            )
            effective = bool(
                diagnostic
                and diagnostic.state == APPLIED
                and operations._expected_effect(
                    "edit_session", operation_id, before, after, source
                )
            )
            if not effective:
                conn.execute("ROLLBACK TO report_operation")
                conn.execute("RELEASE report_operation")
                current = operations._find_entry(before.final_sessions, source_key)
                result = MutationResult(
                    request_id=request_id,
                    outcome_type="no_op",
                    operation_id=None,
                    report_date=report_date,
                    selection_hint=operations._selection_hint(current),
                    snapshot_revision=before.snapshot_revision,
                    error="operation_no_effect",
                    message="操作未产生变化",
                )
            else:
                conn.execute("RELEASE report_operation")
                result = MutationResult(
                    request_id=request_id,
                    outcome_type="operation_committed",
                    operation_id=operation_id,
                    report_date=report_date,
                    selection_hint=operations._post_selection(
                        "edit_session", operation_id, source_key, after
                    ),
                    snapshot_revision=after.snapshot_revision,
                )
            operations._insert_receipt(conn, request_id, signature, result)
            conn.commit()
            return result
        except sqlite3.OperationalError as exc:
            conn.rollback()
            if "locked" in str(exc).lower() or "busy" in str(exc).lower():
                raise DatabaseBusyError() from exc
            raise
        except Exception:
            conn.rollback()
            raise


__all__ = ["edit_session"]
