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
        if (
            rule_type not in {"folder", "keyword"}
            or type(rule_id) is not int
            or rule_id <= 0
        ):
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
    """Publish catalog effects from canonical identity, never display name.

    Declares and marks the effects as changed because callers only invoke this
    helper after a confirmed write to the rule catalog. The unit of work keeps
    per-namespace tracking, so a no-op write path that never reaches this helper
    will not publish unrelated generations.
    """

    ids = tuple(dict.fromkeys(int(value) for value in project_ids))
    if not ids:
        return
    uow.add_effects(DataGenerationNamespace.CLASSIFICATION_CATALOG)
    uow.mark_changed(DataGenerationNamespace.CLASSIFICATION_CATALOG)
    if require_excluded_project_id(conn) in ids:
        uow.add_effects(DataGenerationNamespace.PRIVACY_CATALOG)
        uow.mark_changed(DataGenerationNamespace.PRIVACY_CATALOG)


def add_catalog_effects_for_rule(
    uow: DomainUnitOfWork,
    conn,
    rule_type: str,
    rule_id: int,
) -> None:
    row = _rule_row(conn, rule_type, rule_id)
    if row is None:
        return
    add_catalog_effects_for_project_ids(uow, conn, (int(row["project_id"]),))


def _require_rule_target_project(
    conn,
    project_id: int,
    *,
    allow_excluded: bool,
) -> dict[str, Any]:
    """Validate project identity and mutable rule policy in the command UoW."""

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
        if not allow_excluded or project.get("created_by") != "system":
            raise ProjectRuleWriteError("project_not_found")
        return project

    if (
        project.get("created_by") != "user"
        or int(project.get("enabled") or 0) != 1
    ):
        raise ProjectRuleWriteError("project_not_found")
    return project


def _require_existing_rule_owner(conn, row) -> None:
    _require_rule_target_project(
        conn,
        int(row["project_id"]),
        allow_excluded=True,
    )


def _raise_keyword_integrity(exc: sqlite3.IntegrityError) -> None:
    message = str(exc).casefold()
    if (
        "uq_project_rule_normalized_pattern" in message
        or (
            "project_rule.project_id" in message
            and "project_rule.normalized_pattern" in message
        )
    ):
        raise ProjectRuleWriteError("duplicate_rule") from exc
    raise exc


def _insert_keyword_rule(
    uow: DomainUnitOfWork,
    conn,
    keyword: str,
    project_id: int,
    *,
    allow_excluded: bool,
) -> int:
    cleaned = str(keyword or "").strip()
    normalized = normalize_keyword_pattern(cleaned)
    if not cleaned or not normalized:
        raise ProjectRuleWriteError("invalid_input")
    _require_rule_target_project(
        conn,
        int(project_id),
        allow_excluded=allow_excluded,
    )
    timestamp = now_str()
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
    add_catalog_effects_for_project_ids(uow, conn, (project_id,))
    return int(cursor.lastrowid)


def create_keyword_rule(keyword: str, project_id: int) -> int:
    """Create a normal user-project keyword rule."""

    with _catalog_uow() as uow:
        return _insert_keyword_rule(
            uow,
            uow.connection,
            keyword,
            project_id,
            allow_excluded=False,
        )


def create_excluded_keyword_rule(keyword: str) -> tuple[int, int]:
    """Create a privacy rule for the canonical excluded system project."""

    with _catalog_uow() as uow:
        conn = uow.connection
        project_id = require_excluded_project_id(conn)
        rule_id = _insert_keyword_rule(
            uow,
            conn,
            keyword,
            project_id,
            allow_excluded=True,
        )
        return rule_id, project_id


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
        _require_existing_rule_owner(conn, row)
        if (
            str(row["pattern"] or "") == cleaned
            and str(row["normalized_pattern"] or "") == normalized
        ):
            return True
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
        if cursor.rowcount == 1:
            add_catalog_effects_for_project_ids(
                uow,
                conn,
                (int(row["project_id"]),),
            )
            return True
        return False


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


def _upsert_folder_rule(
    uow: DomainUnitOfWork,
    conn,
    folder_path: str,
    project_id: int,
    *,
    recursive: bool,
    allow_excluded: bool,
) -> tuple[int, bool]:
    folder = str(folder_path or "").strip()
    key = normalize_folder_key(folder)
    if not folder or not key:
        raise ProjectRuleWriteError("invalid_input")
    _require_rule_target_project(
        conn,
        int(project_id),
        allow_excluded=allow_excluded,
    )
    requested_recursive = int(bool(recursive))
    timestamp = now_str()
    existing = conn.execute(
        "SELECT * FROM folder_project_rule WHERE normalized_folder_key = ?",
        (key,),
    ).fetchone()
    if existing is not None and (
        int(existing["project_id"] or 0) == int(project_id)
        and int(existing["recursive"] or 0) == requested_recursive
        and int(existing["enabled"] or 0) == 1
    ):
        return int(existing["id"]), False

    project_ids = [int(project_id)]
    if existing is not None:
        project_ids.append(int(existing["project_id"]))
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
        int(existing["project_id"] or 0) != int(project_id)
        or int(existing["recursive"] or 0) != requested_recursive
    )
    wake_worker = (
        folder_index_state_repository.request_rebuild(conn, rule_id)
        if path_behavior_changed
        else folder_index_state_repository.ensure_pending_state(conn, rule_id)
    )
    add_catalog_effects_for_project_ids(uow, conn, project_ids)
    return rule_id, bool(wake_worker)


def create_or_update_folder_rule(
    folder_path: str,
    project_id: int,
    recursive: bool = True,
) -> int:
    """Create or update a normal user-project folder rule."""

    with _catalog_uow() as uow:
        rule_id, wake_worker = _upsert_folder_rule(
            uow,
            uow.connection,
            folder_path,
            project_id,
            recursive=recursive,
            allow_excluded=False,
        )
    if wake_worker:
        _wake_folder_index_worker_safely()
    return rule_id


def create_or_update_excluded_folder_rule(
    folder_path: str,
    recursive: bool = True,
) -> tuple[int, int]:
    """Create or update a privacy folder rule for the excluded project."""

    with _catalog_uow() as uow:
        conn = uow.connection
        project_id = require_excluded_project_id(conn)
        rule_id, wake_worker = _upsert_folder_rule(
            uow,
            conn,
            folder_path,
            project_id,
            recursive=recursive,
            allow_excluded=True,
        )
    if wake_worker:
        _wake_folder_index_worker_safely()
    return rule_id, project_id


def update_folder_rule(
    rule_id: int,
    folder_path: str,
    recursive: bool = True,
) -> bool:
    folder = str(folder_path or "").strip()
    key = normalize_folder_key(folder)
    if not folder or not key:
        raise ProjectRuleWriteError("invalid_input")
    requested_recursive = int(bool(recursive))
    with _catalog_uow() as uow:
        conn = uow.connection
        row = _rule_row(conn, "folder", rule_id)
        if row is None:
            return False
        _require_existing_rule_owner(conn, row)
        if (
            str(row["normalized_folder_key"] or "") == key
            and int(row["recursive"] or 0) == requested_recursive
        ):
            return True
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
            add_catalog_effects_for_project_ids(
                uow,
                conn,
                (int(row["project_id"]),),
            )
    if changed:
        _wake_folder_index_worker_safely()
    return changed


def delete_folder_rule(rule_id: int) -> bool:
    with _catalog_uow() as uow:
        conn = uow.connection
        row = _rule_row(conn, "folder", rule_id)
        if row is None:
            return False
        _require_existing_rule_owner(conn, row)
        folder_index_state_repository.delete_rule_index(conn, int(rule_id))
        add_catalog_effects_for_project_ids(
            uow,
            conn,
            (int(row["project_id"]),),
        )
        table, extra = _rule_table("folder")
        cursor = conn.execute(
            f"DELETE FROM {table} WHERE id = ?{extra}",
            (int(rule_id),),
        )
        return cursor.rowcount == 1


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
        rows: list[Any] = []
        for rule_type, rule_id in refs:
            row = _rule_row(conn, rule_type, rule_id)
            if row is None:
                raise ValueError("not_found")
            _require_existing_rule_owner(conn, row)
            rows.append(row)
        timestamp = now_str()
        for (rule_type, rule_id), row in zip(refs, rows, strict=True):
            if int(row["enabled"] or 0) == int(requested):
                continue
            table, extra = _rule_table(rule_type)
            cursor = conn.execute(
                f"UPDATE {table} SET enabled = ?, updated_at = ? "
                f"WHERE id = ?{extra}",
                (int(requested), timestamp, int(rule_id)),
            )
            if cursor.rowcount != 1:
                raise ValueError("operation_failed")
            add_catalog_effects_for_project_ids(
                uow,
                conn,
                (int(row["project_id"]),),
            )
        return [
            dict(_rule_row(conn, rule_type, rule_id))
            for rule_type, rule_id in refs
        ]


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
    _require_existing_rule_owner(conn, row)
    requested = int(bool(enabled))
    if int(row["enabled"] or 0) == requested:
        return True
    table, extra = _rule_table(rule_type)
    cursor = conn.execute(
        f"UPDATE {table} SET enabled = ?, updated_at = ? WHERE id = ?{extra}",
        (requested, timestamp or now_str(), int(rule_id)),
    )
    if cursor.rowcount == 1:
        add_catalog_effects_for_project_ids(
            uow,
            conn,
            (int(row["project_id"]),),
        )
        return True
    return False


def delete_rule_in_transaction(
    uow: DomainUnitOfWork,
    conn,
    rule_type: str,
    rule_id: int,
) -> bool:
    row = _rule_row(conn, rule_type, rule_id)
    if row is None:
        return False
    _require_existing_rule_owner(conn, row)
    table, extra = _rule_table(rule_type)
    cursor = conn.execute(
        f"DELETE FROM {table} WHERE id = ?{extra}",
        (int(rule_id),),
    )
    if cursor.rowcount == 1:
        add_catalog_effects_for_project_ids(
            uow,
            conn,
            (int(row["project_id"]),),
        )
        return True
    return False


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
    "create_excluded_keyword_rule",
    "create_keyword_rule",
    "create_or_update_excluded_folder_rule",
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
