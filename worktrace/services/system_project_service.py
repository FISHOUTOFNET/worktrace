"""Canonical access to mandatory system projects.

Normal reads must use :func:`require_system_project_id`. Creation is restricted
to database initialization, migrations, and explicit recovery commands.
"""

from __future__ import annotations

from ..constants import EXCLUDED_PROJECT, UNCATEGORIZED_PROJECT
from ..data_generation_repository import DataGenerationNamespace
from ..db import get_connection, now_str
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


class SystemProjectCatalogUnavailableError(RuntimeError):
    """A mandatory system row is absent or has invalid ownership."""


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
        raise SystemProjectCatalogUnavailableError("system_catalog_unavailable")
    return int(row["id"])


def require_uncategorized_project_id(conn=None) -> int:
    if conn is not None:
        return require_system_project_id(conn, "uncategorized")
    with get_connection() as read_conn:
        return require_system_project_id(read_conn, "uncategorized")


def require_excluded_project_id(conn=None) -> int:
    if conn is not None:
        return require_system_project_id(conn, "excluded")
    with get_connection() as read_conn:
        return require_system_project_id(read_conn, "excluded")


def _effects_for_system_project(
    kind: str,
) -> tuple[DataGenerationNamespace, ...]:
    """Return the generation namespaces affected by mutating one project."""

    base = (
        DataGenerationNamespace.CLASSIFICATION_CATALOG,
        DataGenerationNamespace.REPORT_STRUCTURE,
    )
    if kind == "excluded":
        return (*base, DataGenerationNamespace.PRIVACY_CATALOG)
    return base


def ensure_system_projects() -> dict[str, int]:
    """Repair mandatory system projects from an explicit command boundary."""

    timestamp = now_str()
    with DomainUnitOfWork(
        (
            DataGenerationNamespace.CLASSIFICATION_CATALOG,
            DataGenerationNamespace.PRIVACY_CATALOG,
            DataGenerationNamespace.REPORT_STRUCTURE,
        )
    ) as uow:
        conn = uow.connection
        changed_namespaces: set[DataGenerationNamespace] = set()
        for kind, definition in _SYSTEM_PROJECTS.items():
            existing = conn.execute(
                "SELECT id, created_by FROM project WHERE name = ?",
                (definition["name"],),
            ).fetchone()
            if existing is not None:
                if str(existing["created_by"] or "") != "system":
                    conn.execute(
                        "UPDATE project SET created_by = 'system', updated_at = ? WHERE id = ?",
                        (timestamp, int(existing["id"])),
                    )
                    changed_namespaces.update(
                        _effects_for_system_project(kind)
                    )
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
            changed_namespaces.update(_effects_for_system_project(kind))
        if changed_namespaces:
            uow.mark_changed(*changed_namespaces)
        return {
            kind: require_system_project_id(conn, kind)
            for kind in _SYSTEM_PROJECTS
        }


__all__ = [
    "SystemProjectCatalogUnavailableError",
    "ensure_system_projects",
    "require_excluded_project_id",
    "require_system_project_id",
    "require_uncategorized_project_id",
]
