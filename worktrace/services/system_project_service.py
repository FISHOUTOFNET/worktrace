"""Canonical access to mandatory system projects.

Normal reads must use :func:`require_system_project_id`. Creation is restricted
to database initialization, migrations, and explicit recovery commands.
"""

from __future__ import annotations

from ..constants import EXCLUDED_PROJECT, UNCATEGORIZED_PROJECT
from ..data_generation_repository import DataGenerationNamespace
from ..db import now_str
from ..domain_unit_of_work import DomainUnitOfWork

_SYSTEM_PROJECTS = {
    "uncategorized": {
        "name": UNCATEGORIZED_PROJECT,
        "description": "",
        "enabled": 1,
    },
    "excluded": {
        "name": EXCLUDED_PROJECT,
        "description": "命中后匿名记录",
        "enabled": 0,
    },
}


def _definition(kind: str) -> dict:
    try:
        return _SYSTEM_PROJECTS[str(kind)]
    except KeyError as exc:
        raise ValueError("unknown_system_project") from exc


def require_system_project_id(conn, kind: str) -> int:
    """Return a mandatory system project id without mutating the database."""

    definition = _definition(kind)
    row = conn.execute(
        """
        SELECT id
        FROM project
        WHERE name = ? AND created_by = 'system'
        """,
        (definition["name"],),
    ).fetchone()
    if row is None:
        raise ValueError("system_catalog_repair_required")
    return int(row["id"])


def require_uncategorized_project_id(conn) -> int:
    return require_system_project_id(conn, "uncategorized")


def require_excluded_project_id(conn) -> int:
    return require_system_project_id(conn, "excluded")


def ensure_system_projects() -> dict[str, int]:
    """Repair mandatory system projects from an explicit command boundary."""

    timestamp = now_str()
    with DomainUnitOfWork(
        (
            DataGenerationNamespace.CLASSIFICATION_CATALOG,
            DataGenerationNamespace.PRIVACY_CATALOG,
        )
    ) as uow:
        conn = uow.connection
        changed = False
        for definition in _SYSTEM_PROJECTS.values():
            existing = conn.execute(
                "SELECT id FROM project WHERE name = ?",
                (definition["name"],),
            ).fetchone()
            if existing is not None:
                continue
            conn.execute(
                """
                INSERT INTO project(
                    name, description, language, is_archived, enabled,
                    created_by, created_at, updated_at
                ) VALUES (?, ?, '中文', 0, ?, 'system', ?, ?)
                """,
                (
                    definition["name"],
                    definition["description"],
                    int(definition["enabled"]),
                    timestamp,
                    timestamp,
                ),
            )
            changed = True
        if changed:
            uow.mark_changed()
        return {
            kind: require_system_project_id(conn, kind)
            for kind in _SYSTEM_PROJECTS
        }


__all__ = [
    "ensure_system_projects",
    "require_excluded_project_id",
    "require_system_project_id",
    "require_uncategorized_project_id",
]
