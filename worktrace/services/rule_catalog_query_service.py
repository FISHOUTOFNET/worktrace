"""Read-side rule catalog capabilities used by cross-domain application workflows."""
from __future__ import annotations

from .rule_catalog_command_service import RuleRef


def list_project_rule_refs_in_transaction(conn, project_id: int) -> list[RuleRef]:
    """Return stable rule identities owned by one project in the caller transaction."""

    requested_id = int(project_id)
    refs: list[RuleRef] = [
        ("keyword", int(row["id"]))
        for row in conn.execute(
            "SELECT id FROM project_rule WHERE project_id = ? ORDER BY id",
            (requested_id,),
        ).fetchall()
    ]
    refs.extend(
        ("folder", int(row["id"]))
        for row in conn.execute(
            "SELECT id FROM folder_project_rule WHERE project_id = ? ORDER BY id",
            (requested_id,),
        ).fetchall()
    )
    return refs


__all__ = ["list_project_rule_refs_in_transaction"]
