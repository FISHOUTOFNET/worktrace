from __future__ import annotations

import time

from ..db import get_connection, get_db_path, now_str

_SETTING_CACHE_TTL_SECONDS = 2.0
_SETTING_CACHE: dict[tuple[str, str], tuple[float, str | None]] = {}


def clear_settings_cache(key: str | None = None) -> None:
    if key is None:
        _SETTING_CACHE.clear()
        return
    db_key = _settings_db_key()
    _SETTING_CACHE.pop((db_key, key), None)


def _settings_db_key() -> str:
    return str(get_db_path().resolve())


def get_setting(key: str, default: str | None = None) -> str | None:
    cache_key = (_settings_db_key(), key)
    now = time.monotonic()
    cached = _SETTING_CACHE.get(cache_key)
    if cached is not None and cached[0] >= now:
        value = cached[1]
        return value if value is not None else default

    with get_connection() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    value = row["value"] if row else None
    _SETTING_CACHE[cache_key] = (now + _SETTING_CACHE_TTL_SECONDS, value)
    return value if value is not None else default


def set_setting(key: str, value: str) -> None:
    ts = now_str()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO settings(key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
            """,
            (key, value, ts),
        )
    _SETTING_CACHE[(_settings_db_key(), key)] = (time.monotonic() + _SETTING_CACHE_TTL_SECONDS, value)


def get_bool_setting(key: str, default: bool = False) -> bool:
    raw = get_setting(key)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() == "true"


def get_int_setting(key: str, default: int) -> int:
    raw = get_setting(key)
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
