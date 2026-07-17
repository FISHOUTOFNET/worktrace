"""Canonical command owner for keyword and folder rule catalog mutations."""

from __future__ import annotations

from typing import Any, Iterable

from ..constants import EXCLUDED_PROJECT
from ..data_generation_repository import DataGenerationNamespace
from ..db import now_str
from ..domain_unit_of_work import DomainUnitOfWork
from ..path_utils import normalize_folder_key

RuleRef = tuple[str, int]


def _catalog_uow() -> DomainUnitOfWork:
    return DomainUnitOfWork((DataGenerationNamespace.CLASSIFICATION_CATALOG,))


def normalize_rule_refs(rules: Iterable[dict[str, Any] | RuleRef]) -> list[RuleRef]:
    result: list[RuleRef] = []
    seen: set[RuleRef] = set()
    for value in rules:
        if isinstance(value, tuple) and len(value) == 2:
            rule_type, rule_id = value
        elif isinstance(value, dict):
            rule_type = value.get("rule_type")
            rule_id = value.get("rule_id")
        else:
            raise ValueError("invalid_input")
        if rule_type not in {"folder", "keyword"} or type(rule_id) is not int or rule_id <= 0:
            raise ValueError("invalid_input")
        ref = (str(rule_type), int(rule_id))
        if ref not in seen:
            seen.add(ref)
            result.append(ref)
    if not result:
        raise ValueError("invalid_input")
    return result


def add_catalog_effects_for_project_id(
    uow: DomainUnitOfWork,
    conn,
    project_id: int,
) -> None:
    uow.add_effects(DataGenerationNamespace.CLASSIFICATION_CATALOG)
    row = conn.execute(
        "SELECT name FROM project WHERE id = ?",
        (int(project_id),),
    ).fetchone()
    if row is not None and str(row["name"] or "") == EXCLUDED_PROJECT:
        uow.add_effects(DataGenerationNamespace.PRIVACY_CATALOG)


def add_catalog_effects_for_rule(
    uow: DomainUnitOfWork,
    conn,
    rule_type: str,
    rule_id: int,
) -> None:
    row = _rule_row(conn, rule_type, rule_id)
    if row is None:
        uow.add_effects(DataGenerationNamespace.CLASSIFICATION_CATALOG)
        return
    add_catalog_effects_for_project_id(uow, conn, int(row["project_id"]))


def create_keyword_rule(keyword: str, project_id: int) -> int:
    cleaned = str(keyword or "").strip()
    if not cleaned:
        raise ValueError("keyword is required")
    timestamp = now_str()
    with _catalog_uow() as uow:
        conn = uow.connection
        add_catalog_effects_for_project_id(uow, conn, project_id)
        cursor = conn.execute(
            """
            INSERT INTO project_rule(
                project_id, rule_type, pattern, enabled, created_by,
                created_at, updated_at
            ) VALUES (?, 'keyword', ?, 1, 'user', ?, ?)
            """,
            (int(project_id), cleaned, timestamp, timestamp),
        )
        return int(cursor.lastrowid)


def update_keyword_rule(rule_id: int, keyword: str) -> bool:
    cleaned = str(keyword or "").strip()
    if not cleaned:
        raise ValueError("keyword is required")
    with _catalog_uow() as uow:
        conn = uow.connection
        row = _rule_row(conn, "keyword", rule_id)
        if row is None:
            return False
        if str(row["pattern"] or "") == cleaned:
            return True
        add_catalog_effects_for_project_id(uow, conn, int(row["project_id"]))
        cursor = conn.execute(
            """
            UPDATE project_rule
            SET pattern = ?, updated_at = ?
            WHERE id = ? AND rule_type = 'keyword'
            """,
            (cleaned, now_str(), int(rule_id)),
        )
        return cursor.rowcount == 1


def delete_keyword_rule(rule_id: int) -> bool:
    with _catalog_uow() as uow:
        return delete_rule_in_transaction(uow, uow.connection, "keyword", rule_id)


def set_keyword_rule_enabled(rule_id: int, enabled: bool) -> bool:
    with _catalog_uow() as uow:
        return set_rule_enabled_in_transaction(
            uow,
            uow.connection,
            "keyword",
            rule_id,
            bool(enabled),
        )


def create_or_update_folder_rule(
    folder_path: str,
    project_id: int,
    recursive: bool = True,
) -> int:
    folder = str(folder_path or "").strip()
    key = normalize_folder_key(folder)
    if not folder or not key:
        raise ValueError("folder path is required")
    requested_recursive = int(bool(recursive))
    timestamp = now_str()
    changed = False
    with _catalog_uow() as uow:
        conn = uow.connection
        existing = conn.execute(
            "SELECT * FROM folder_project_rule WHERE normalized_folder_key = ?",
            (key,),
        ).fetchone()
        if existing is not None:
            rule_id = int(existing["id"])
            if (
                str(existing["folder_path"] or "") == folder
                and int(existing["project_id"] or 0) == int(project_id)
                and int(existing["recursive"] or 0) == requested_recursive
                and int(existing["enabled"] or 0) == 1
            ):
                return rule_id
        add_catalog_effects_for_project_id(uow, conn, project_id)
        cursor = conn.execute(
            """
            INSERT INTO folder_project_rule(
                folder_path, normalized_folder_key, project_id, recursive,
                enabled, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, 1, ?, ?)
            ON CONFLICT(normalized_folder_key) DO UPDATE SET
                folder_path = excluded.folder_path,
                project_id = excluded.project_id,
                recursive = excluded.recursive,
                enabled = 1,
                updated_at = excluded.updated_at
            """,
            (
                folder,
                key,
                int(project_id),
                requested_recursive,
                timestamp,
                timestamp,
            ),
        )
        row = conn.execute(
            "SELECT id FROM folder_project_rule WHERE normalized_folder_key = ?",
            (key,),
        ).fetchone()
        rule_id = int(row["id"] if row else cursor.lastrowid)
        changed = True
    if changed:
        from .folder_index_service import request_rebuild_for_rule

        request_rebuild_for_rule(rule_id)
    return rule_id


def update_folder_rule(
    rule_id: int,
    folder_path: str,
    recursive: bool = True,
) -> bool:
    folder = str(folder_path or "").strip()
    key = normalize_folder_key(folder)
    if not folder or not key:
        raise ValueError("folder path is required")
    requested_recursive = int(bool(recursive))
    with _catalog_uow() as uow:
        conn = uow.connection
        row = _rule_row(conn, "folder", rule_id)
        if row is None:
            return False
        if (
            str(row["folder_path"] or "") == folder
            and str(row["normalized_folder_key"] or "") == key
            and int(row["recursive"] or 0) == requested_recursive
        ):
            return True
        add_catalog_effects_for_project_id(uow, conn, int(row["project_id"]))
        cursor = conn.execute(
            """
            UPDATE folder_project_rule
            SET folder_path = ?, normalized_folder_key = ?, recursive = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (folder, key, requested_recursive, now_str(), int(rule_id)),
        )
        changed = cursor.rowcount == 1
    if changed:
        from .folder_index_service import request_rebuild_for_rule

        request_rebuild_for_rule(int(rule_id))
    return changed


def delete_folder_rule(rule_id: int) -> bool:
    with _catalog_uow() as uow:
        deleted = delete_rule_in_transaction(
            uow,
            uow.connection,
            "folder",
            rule_id,
        )
    if deleted:
        from .folder_index_service import delete_index_for_rule

        delete_index_for_rule(int(rule_id))
    return deleted


def set_folder_rule_enabled(rule_id: int, enabled: bool) -> bool:
    with _catalog_uow() as uow:
        return set_rule_enabled_in_transaction(
            uow,
            uow.connection,
            "folder",
            rule_id,
            bool(enabled),
        )


def set_rules_enabled(
    rules: Iterable[dict[str, Any] | RuleRef],
    enabled: bool,
) -> list[dict[str, Any]]:
    refs = normalize_rule_refs(rules)
    requested = bool(enabled)
    with _catalog_uow() as uow:
        conn = uow.connection
        rows: list[dict[str, Any]] = []
        for rule_type, rule_id in refs:
            row = _rule_row(conn, rule_type, rule_id)
            if row is None:
                raise ValueError("not_found")
            rows.append(dict(row))
        timestamp = now_str()
        for (rule_type, rule_id), row in zip(refs, rows, strict=True):
            if int(row["enabled"] or 0) == int(requested):
                continue
            add_catalog_effects_for_project_id(uow, conn, int(row["project_id"]))
            table, extra = _rule_table(rule_type)
            cursor = conn.execute(
                f"UPDATE {table} SET enabled = ?, updated_at = ? WHERE id = ?{extra}",
                (int(requested), timestamp, int(rule_id)),
            )
            if cursor.rowcount != 1:
                raise ValueError("operation_failed")
        return [dict(_rule_row(conn, rule_type, rule_id)) for rule_type, rule_id in refs]


def set_rule_enabled_in_transaction(
    uow: DomainUnitOfWork,
    conn,
    rule_type: str,
    rule_id: int,
    enabled: bool,
    *,
    timestamp: str | None = None,
) -> bool:
    row = _rule_row(conn, rule_type, rule_id)
    if row is None:
        return False
    requested = int(bool(enabled))
    if int(row["enabled"] or 0) == requested:
        return True
    add_catalog_effects_for_project_id(uow, conn, int(row["project_id"]))
    table, extra = _rule_table(rule_type)
    cursor = conn.execute(
        f"UPDATE {table} SET enabled = ?, updated_at = ? WHERE id = ?{extra}",
        (requested, timestamp or now_str(), int(rule_id)),
    )
    return cursor.rowcount == 1


def delete_rule_in_transaction(
    uow: DomainUnitOfWork,
    conn,
    rule_type: str,
    rule_id: int,
) -> bool:
    row = _rule_row(conn, rule_type, rule_id)
    if row is None:
        return False
    add_catalog_effects_for_project_id(uow, conn, int(row["project_id"]))
    table, extra = _rule_table(rule_type)
    cursor = conn.execute(
        f"DELETE FROM {table} WHERE id = ?{extra}",
        (int(rule_id),),
    )
    return cursor.rowcount == 1


def _rule_row(conn, rule_type: str, rule_id: int):
    if rule_type == "folder":
        return conn.execute(
            """
            SELECT id, folder_path, normalized_folder_key, project_id,
                   recursive, enabled, created_at, updated_at
            FROM folder_project_rule
            WHERE id = ?
            """,
            (int(rule_id),),
        ).fetchone()
    if rule_type == "keyword":
        return conn.execute(
            """
            SELECT id, pattern, project_id, enabled, created_at, updated_at
            FROM project_rule
            WHERE id = ? AND rule_type = 'keyword'
            """,
            (int(rule_id),),
        ).fetchone()
    raise ValueError("invalid_input")


def _rule_table(rule_type: str) -> tuple[str, str]:
    if rule_type == "folder":
        return "folder_project_rule", ""
    if rule_type == "keyword":
        return "project_rule", " AND rule_type = 'keyword'"
    raise ValueError("invalid_input")


__all__ = [
    "RuleRef",
    "add_catalog_effects_for_project_id",
    "add_catalog_effects_for_rule",
    "create_keyword_rule",
    "create_or_update_folder_rule",
    "delete_folder_rule",
    "delete_keyword_rule",
    "delete_rule_in_transaction",
    "normalize_rule_refs",
    "set_folder_rule_enabled",
    "set_keyword_rule_enabled",
    "set_rule_enabled_in_transaction",
    "set_rules_enabled",
    "update_folder_rule",
    "update_keyword_rule",
]
