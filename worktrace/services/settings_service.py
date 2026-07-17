"""Durable settings with explicit mutation classes and generation effects."""

from __future__ import annotations

import time
from enum import StrEnum
from typing import Mapping

from ..data_generation_repository import DataGenerationNamespace
from ..db import get_connection, get_db_path, now_str
from ..domain_unit_of_work import DomainUnitOfWork

_SETTING_CACHE_TTL_SECONDS = 2.0
_SETTING_CACHE: dict[tuple[str, str], tuple[float, str | None]] = {}


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
    "first_run_notice_accepted",
    "accepted_privacy_notice_version",
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


def clear_settings_cache(key: str | None = None) -> None:
    if key is None:
        _SETTING_CACHE.clear()
        return
    _SETTING_CACHE.pop((_settings_db_key(), key), None)


def _settings_db_key() -> str:
    return str(get_db_path().resolve())


def _page_read_connection():
    from .page_read_context import current_page_read_context

    context = current_page_read_context()
    return context.conn if context is not None else None


def get_setting(key: str, default: str | None = None, *, conn=None) -> str | None:
    effective_conn = conn if conn is not None else _page_read_connection()
    if effective_conn is not None:
        row = effective_conn.execute(
            "SELECT value FROM settings WHERE key = ?",
            (key,),
        ).fetchone()
        value = row["value"] if row else None
        return value if value is not None else default
    cache_key = (_settings_db_key(), key)
    now = time.monotonic()
    cached = _SETTING_CACHE.get(cache_key)
    if cached is not None and cached[0] >= now:
        value = cached[1]
        return value if value is not None else default
    with get_connection() as own_conn:
        row = own_conn.execute(
            "SELECT value FROM settings WHERE key = ?",
            (key,),
        ).fetchone()
    value = row["value"] if row else None
    _SETTING_CACHE[cache_key] = (now + _SETTING_CACHE_TTL_SECONDS, value)
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

    changed_keys: list[str] = []
    with DomainUnitOfWork(effects) as uow:
        conn = uow.connection
        timestamp = now_str()
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
            changed_keys.append(key)
        if changed_keys:
            uow.mark_changed()

    for key in changed_keys:
        clear_settings_cache(key)


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
