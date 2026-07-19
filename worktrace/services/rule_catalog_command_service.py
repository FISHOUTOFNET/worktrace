"""Canonical command owner for keyword and folder rule catalog mutations."""

from __future__ import annotations

import logging
import sqlite3
from typing import Any, Iterable

from ..data_generation_repository import DataGenerationNamespace
from ..db import now_str
from ..domain_unit_of_work import DomainUnitOfWork
from ..path_utils import normalize_folder_key
from . import folder_index_service, folder_index_state_repository
from .keyword_rule_policy import ProjectRuleWriteError, normalize_keyword_pattern
from .system_project_service import require_excluded_project_id

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


def add_catalog_effects_for_project_ids(
    uow: DomainUnitOfWork,
    conn,
    project_ids: Iterable[int],
) -> None:
    """Publish catalog effects from canonical project identity, never display name."""

    uow.add_effects(DataGenerationNamespace.CLASSIFICATION_CATALOG)
    ids = tuple(dict.fromkeys(int(value) for value in project_ids))
    if not ids:
        return
    if require_excluded_project_id(conn) in ids:
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
    add_catalog_effects_for_project_ids(uow, conn, (int(row["project_id"]),))


def _require_rule_target_project(conn, project_id: int) -> dict[str, Any]:
    """Require a current user project or the canonical excluded system project."""

    requested_id = int(project_id)
    row = conn.execute(
        "SELECT * FROM project WHERE id = ?",
        (requested_id,),
    ).fetchone()
    project = dict(row) if row is not None else None
    if (
        project is None
        or int(project.get("is_deleted") or 0) == 1
        or int(project.get("is_archived") or 0) == 1
    ):
        raise ProjectRuleWriteError("project_not_found")

    excluded_id = require_excluded_project_id(conn)
    if requested_id == excluded_id:
        if project.get("created_by") != "system":
            raise ProjectRuleWriteError("project_not_found")
        return project

    if (
        project.get("created_by") != "user"
        or int(project.get("enabled") or 0) != 1
    ):
        raise ProjectRuleWriteError("project_not_found")
    return project


def _raise_keyword_integrity(exc: sqlite3.IntegrityError) -> None:
    message = str(exc).casefold()
    if (
        "uq_project_rule_normalized_pattern" in message
        or "project_rule.project_id" in message
        and "project_rule.normalized_pattern" in message
    ):
        raise ProjectRuleWriteError("duplicate_rule") from exc
    raise exc


def create_keyword_rule(keyword: str, project_id: int) -> int:
    cleaned = str(keyword or "").strip()
    normalized = normalize_keyword_pattern(cleaned)
    if not cleaned or not normalized:
        raise ProjectRuleWriteError("invalid_input")
    timestamp = now_str()
    with _catalog_uow() as uow:
        conn = uow.connection
        _require_rule_target_project(conn, int(project_id))
        add_catalog_effects_for_project_ids(uow, conn, (project_id,))
        try:
            cursor = conn.execute(
                """
                INSERT INTO project_rule(
                    project_id, rule_type, pattern, normalized_pattern,
                    enabled, created_by, created_at, updated_at
                ) VALUES (?, 'keyword', ?, ?, 1, 'user', ?, ?)
                """,
                (
                    int(project_id),
                    cleaned,
                    normalized,
                    timestamp,
                    timestamp,
                ),
            )
        except sqlite3.IntegrityError as exc:
            _raise_keyword_integrity(exc)
        return int(cursor.lastrowid)


def update_keyword_rule(rule_id: int, keyword: str) -> bool:
    cleaned = str(keyword or "").strip()
    normalized = normalize_keyword_pattern(cleaned)
    if not cleaned or not normalized:
        raise ProjectRuleWriteError("invalid_input")
    with _catalog_uow() as uow:
        conn = uow.connection
        row = _rule_row(conn, "keyword", rule_id)
        if row is None:
            return False
        _require_rule_target_project(conn, int(row["project_id"]))
        if (
            str(row["pattern"] or "") == cleaned
            and str(row["normalized_pattern"] or "") == normalized
        ):
            return True
        add_catalog_effects_for_project_ids(uow, conn, (int(row["project_id"]),))
        try:
            cursor = conn.execute(
                """
                UPDATE project_rule
                SET pattern = ?, normalized_pattern = ?, updated_at = ?
                WHERE id = ? AND rule_type = 'keyword'
                """,
                (cleaned, normalized, now_str(), int(rule_id)),
            )
        except sqlite3.IntegrityError as exc:
            _raise_keyword_integrity(exc)
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
    wake_worker = False
    with _catalog_uow() as uow:
        conn = uow.connection
        _require_rule_target_project(conn, int(project_id))
        existing = conn.execute(
            "SELECT * FROM folder_project_rule WHERE normalized_folder_key = ?",
            (key,),
        ).fetchone()
        if existing is not None:
            rule_id = int(existing["id"])
            if (
                str(existing["normalized_folder_key"] or "") == key
                and int(existing["project_id"] or 0) == int(project_id)
                and int(existing["recursive"] or 0) == requested_recursive
                and int(existing["enabled"] or 0) == 1
            ):
                return rule_id
        project_ids = [int(project_id)]
        if existing is not None:
            project_ids.append(int(existing["project_id"]))
        add_catalog_effects_for_project_ids(uow, conn, project_ids)
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
        path_behavior_changed = existing is None or (
            str(existing["normalized_folder_key"] or "") != key
            or int(existing["recursive"] or 0) != requested_recursive
        )
        wake_worker = (
            folder_index_state_repository.request_rebuild(conn, rule_id)
            if path_behavior_changed
            else folder_index_state_repository.ensure_pending_state(conn, rule_id)
        )
    if wake_worker:
        _wake_folder_index_worker_safely()
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
        _require_rule_target_project(conn, int(row["project_id"]))
        if (
            str(row["normalized_folder_key"] or "") == key
            and int(row["recursive"] or 0) == requested_recursive
        ):
            return True
        add_catalog_effects_for_project_ids(uow, conn, (int(row["project_id"]),))
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
            folder_index_state_repository.request_rebuild(conn, int(rule_id))
    if changed:
        _wake_folder_index_worker_safely()
    return changed


def delete_folder_rule(rule_id: int) -> bool:
    with _catalog_uow() as uow:
        folder_index_state_repository.delete_rule_index(
            uow.connection,
            int(rule_id),
        )
        deleted = delete_rule_in_transaction(
            uow,
            uow.connection,
            "folder",
            rule_id,
        )
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
            add_catalog_effects_for_project_ids(uow, conn, (int(row["project_id"]),))
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
    add_catalog_effects_for_project_ids(uow, conn, (int(row["project_id"]),))
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
    add_catalog_effects_for_project_ids(uow, conn, (int(row["project_id"]),))
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
            SELECT id, pattern, normalized_pattern, project_id, enabled,
                   created_at, updated_at
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


def _wake_folder_index_worker_safely() -> None:
    try:
        folder_index_service.wake_folder_index_worker()
    except Exception:
        logging.exception("folder index worker wake failed")


__all__ = [
    "ProjectRuleWriteError",
    "RuleRef",
    "add_catalog_effects_for_project_ids",
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
