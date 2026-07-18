"""Durable settings with explicit mutation classes and one-version cache."""

from __future__ import annotations

import threading
from enum import StrEnum
from typing import Mapping

from ..data_generation_repository import DataGenerationNamespace
from ..db import get_connection, get_db_key, now_str
from ..domain_unit_of_work import DomainUnitOfWork
from ..generation_clock import generation

_SETTING_CACHE_LOCK = threading.RLock()
_SETTING_CACHE_DATABASE_KEY: str | None = None
_SETTING_CACHE_GENERATION: int | None = None
_SETTING_CACHE: dict[str, str | None] = {}


class SettingMutationClass(StrEnum):
    USER = "user"
    REPORT = "report"
    PRIVACY = "privacy"
    OPERATIONAL = "operational"


_REPORT_SETTING_KEYS = {
    "context_carry_minutes",
    "unrecorded_gap_boundary_seconds",
}
_PRIVACY_SETTING_KEYS = {
    "clipboard_capture_enabled",
}
_OPERATIONAL_SETTING_KEYS = {
    "collector_status",
    "last_collector_heartbeat",
    "last_shutdown_at",
    "collector_health_state",
    "collector_last_successful_observation_at",
    "collector_consecutive_failures",
    "collector_last_failure_phase",
    "collector_last_failure_kind",
    "collector_last_failure_at",
    "collector_last_recovery_at",
    "collector_last_recovery_failure_at",
}
_OPERATIONAL_SETTING_PREFIXES = ("maintenance.", "runtime.")


def setting_mutation_class(key: str) -> SettingMutationClass:
    normalized = str(key or "").strip()
    if normalized in _REPORT_SETTING_KEYS:
        return SettingMutationClass.REPORT
    if normalized in _PRIVACY_SETTING_KEYS:
        return SettingMutationClass.PRIVACY
    if normalized in _OPERATIONAL_SETTING_KEYS or normalized.startswith(
        _OPERATIONAL_SETTING_PREFIXES
    ):
        return SettingMutationClass.OPERATIONAL
    return SettingMutationClass.USER


def _effects_for_classification(
    classification: SettingMutationClass,
) -> tuple[DataGenerationNamespace, ...]:
    if classification is SettingMutationClass.OPERATIONAL:
        return ()
    if classification is SettingMutationClass.REPORT:
        return (
            DataGenerationNamespace.SETTINGS,
            DataGenerationNamespace.REPORT_STRUCTURE,
        )
    if classification is SettingMutationClass.PRIVACY:
        return (
            DataGenerationNamespace.SETTINGS,
            DataGenerationNamespace.PRIVACY_CATALOG,
        )
    return (DataGenerationNamespace.SETTINGS,)


def _select_cache_snapshot(database_key: str, current_generation: int) -> None:
    global _SETTING_CACHE_DATABASE_KEY, _SETTING_CACHE_GENERATION
    if (
        _SETTING_CACHE_DATABASE_KEY == database_key
        and _SETTING_CACHE_GENERATION == int(current_generation)
    ):
        return
    _SETTING_CACHE.clear()
    _SETTING_CACHE_DATABASE_KEY = database_key
    _SETTING_CACHE_GENERATION = int(current_generation)


def clear_settings_cache(key: str | None = None) -> None:
    """Test/maintenance hook; ordinary writes rely on generation change.

    A full reset is also the post-commit handoff used by the exclusive encrypted
    import path, whose low-level SQLite transaction cannot use ``DomainUnitOfWork``.
    """

    global _SETTING_CACHE_DATABASE_KEY, _SETTING_CACHE_GENERATION
    reset_generation_clock = key is None
    with _SETTING_CACHE_LOCK:
        if key is None:
            _SETTING_CACHE.clear()
            _SETTING_CACHE_DATABASE_KEY = None
            _SETTING_CACHE_GENERATION = None
        else:
            _SETTING_CACHE.pop(str(key), None)
    if reset_generation_clock:
        from ..generation_clock import clear as clear_generation_clock

        clear_generation_clock(get_db_key())


def _page_read_connection():
    from .page_read_context import current_page_read_context

    context = current_page_read_context()
    return context.conn if context is not None else None


def _read_setting(connection, key: str, default: str | None) -> str | None:
    row = connection.execute(
        "SELECT value FROM settings WHERE key = ?",
        (key,),
    ).fetchone()
    value = row["value"] if row else None
    return value if value is not None else default


def get_setting(key: str, default: str | None = None, *, conn=None) -> str | None:
    effective_conn = conn if conn is not None else _page_read_connection()
    if effective_conn is not None:
        return _read_setting(effective_conn, key, default)

    if setting_mutation_class(key) is SettingMutationClass.OPERATIONAL:
        with get_connection() as own_conn:
            return _read_setting(own_conn, key, default)

    normalized_key = str(key)
    while True:
        database_key = get_db_key()
        current_generation = generation(DataGenerationNamespace.SETTINGS)
        with _SETTING_CACHE_LOCK:
            _select_cache_snapshot(database_key, current_generation)
            if normalized_key in _SETTING_CACHE:
                value = _SETTING_CACHE[normalized_key]
                return value if value is not None else default
        with get_connection() as own_conn:
            value = _read_setting(own_conn, normalized_key, None)
        if generation(DataGenerationNamespace.SETTINGS) != current_generation:
            continue
        with _SETTING_CACHE_LOCK:
            _select_cache_snapshot(database_key, current_generation)
            _SETTING_CACHE[normalized_key] = value
        return value if value is not None else default


def set_setting(
    key: str,
    value: str,
    *,
    mutation_class: SettingMutationClass | str | None = None,
) -> None:
    set_settings({str(key): str(value)}, mutation_class=mutation_class)


def set_settings(
    values: Mapping[str, str],
    *,
    mutation_class: SettingMutationClass | str | None = None,
) -> None:
    normalized = {
        str(key).strip(): str(value)
        for key, value in values.items()
        if str(key).strip()
    }
    if not normalized:
        return
    forced_class = (
        SettingMutationClass(str(mutation_class))
        if mutation_class is not None
        else None
    )
    classifications = {
        key: forced_class or setting_mutation_class(key)
        for key in normalized
    }
    effects: set[DataGenerationNamespace] = set()
    for classification in classifications.values():
        effects.update(_effects_for_classification(classification))

    with DomainUnitOfWork(effects) as uow:
        conn = uow.connection
        timestamp = now_str()
        changed = False
        for key, value in normalized.items():
            row = conn.execute(
                "SELECT value FROM settings WHERE key = ?",
                (key,),
            ).fetchone()
            if row is not None and str(row["value"] or "") == value:
                continue
            conn.execute(
                """
                INSERT INTO settings(key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = excluded.updated_at
                """,
                (key, value, timestamp),
            )
            changed = True
        if changed:
            uow.mark_changed()


def get_bool_setting(key: str, default: bool = False, *, conn=None) -> bool:
    raw = get_setting(key, conn=conn)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() == "true"


def get_int_setting(key: str, default: int, *, conn=None) -> int:
    raw = get_setting(key, conn=conn)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def get_list_setting(key: str, default: list[str] | None = None) -> list[str]:
    raw = get_setting(key)
    if raw is None:
        return list(default or [])
    return [item.strip() for item in raw.split(",") if item.strip()]


def set_list_setting(key: str, values: list[str]) -> None:
    set_setting(key, ",".join(item.strip() for item in values if item.strip()))


__all__ = [
    "SettingMutationClass",
    "clear_settings_cache",
    "get_bool_setting",
    "get_int_setting",
    "get_list_setting",
    "get_setting",
    "set_list_setting",
    "set_setting",
    "set_settings",
    "setting_mutation_class",
]
