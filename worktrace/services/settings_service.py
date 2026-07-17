"""Durable application settings with explicit generation effects."""

from __future__ import annotations

import time

from ..data_generation_repository import DataGenerationNamespace
from ..db import get_connection, get_db_path, now_str
from ..mutation_effects import add_mutation_effects, settings_mutation

_SETTING_CACHE_TTL_SECONDS = 2.0
_SETTING_CACHE: dict[tuple[str, str], tuple[float, str | None]] = {}
_STRUCTURAL_SETTING_KEYS = {
    "context_carry_minutes",
    "unrecorded_gap_boundary_seconds",
}
_PRIVACY_SETTING_KEYS = {
    "clipboard_capture_enabled",
    "first_run_notice_accepted",
    "accepted_privacy_notice_version",
}


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


@settings_mutation
def set_setting(key: str, value: str) -> None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT value FROM settings WHERE key = ?",
            (key,),
        ).fetchone()
        if row is not None and str(row["value"] or "") == str(value):
            return
        if key in _STRUCTURAL_SETTING_KEYS:
            add_mutation_effects(DataGenerationNamespace.REPORT_STRUCTURE)
        if key in _PRIVACY_SETTING_KEYS:
            add_mutation_effects(DataGenerationNamespace.PRIVACY_CATALOG)
        conn.execute(
            """
            INSERT INTO settings(key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_at = excluded.updated_at
            """,
            (key, value, now_str()),
        )
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
