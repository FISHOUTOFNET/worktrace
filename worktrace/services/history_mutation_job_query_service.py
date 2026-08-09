"""Read-side guards for durable history mutation jobs."""
from __future__ import annotations

from collections.abc import Iterable

from .rule_catalog_command_service import RuleRef

_ACTIVE_STATUSES = ("pending", "running")


def has_active_jobs_for_rule_refs_in_transaction(
    conn,
    rule_refs: Iterable[RuleRef],
) -> bool:
    """Return whether any supplied rule identity is owned by an active history job."""

    requested = {(str(rule_type), int(rule_id)) for rule_type, rule_id in rule_refs}
    if not requested:
        return False
    rows = conn.execute(
        """
        SELECT ref.rule_type, ref.rule_id
        FROM history_mutation_job job
        JOIN history_mutation_job_rule ref ON ref.job_id = job.id
        WHERE job.status IN (?, ?)
        """,
        _ACTIVE_STATUSES,
    ).fetchall()
    return any(
        (str(row["rule_type"]), int(row["rule_id"])) in requested
        for row in rows
    )


__all__ = ["has_active_jobs_for_rule_refs_in_transaction"]
