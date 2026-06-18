from __future__ import annotations

from ..db import get_connection, now_str


def get_setting(key: str, default: str | None = None) -> str | None:
    with get_connection() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


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
