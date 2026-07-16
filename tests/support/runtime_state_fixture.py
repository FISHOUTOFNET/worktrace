"""Explicit test-only adapter for constructing typed runtime activity state."""

from __future__ import annotations

import json
from typing import Any

from worktrace.db import get_db_key
from worktrace.services.runtime_activity_state_service import (
    clear_runtime_activity_state,
    get_runtime_activity_snapshot,
    publish_runtime_activity_snapshot,
)

CURRENT_ACTIVITY_SNAPSHOT = "current_activity_snapshot"
PENDING_SHORT_SECONDS = "pending_short_seconds"
PENDING_CARRY_PROVENANCE = "pending_short_carry_provenance"
_RAW_SNAPSHOT_FIXTURES: dict[str, str] = {}


def set_setting(key: str, value: str) -> None:
    """Translate historical fixture vocabulary into the typed runtime owner."""

    if key == CURRENT_ACTIVITY_SNAPSHOT:
        database_key = get_db_key()
        raw = str(value or "")
        if not raw:
            _RAW_SNAPSHOT_FIXTURES.pop(database_key, None)
            clear_runtime_activity_state("test_fixture_clear")
            return
        try:
            parsed: Any = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError("runtime snapshot fixture must be valid JSON") from exc
        if not isinstance(parsed, dict):
            raise ValueError("runtime snapshot fixture must be a JSON object")
        _RAW_SNAPSHOT_FIXTURES[database_key] = raw
        publish_runtime_activity_snapshot(parsed, "test_fixture_publish")
        return
    if key in {PENDING_SHORT_SECONDS, PENDING_CARRY_PROVENANCE}:
        # Pending-short state was removed from production. Historical tests may
        # still seed it while migrating, but the effective value is always empty.
        return
    raise KeyError(f"unsupported runtime fixture key: {key}")


def get_setting(key: str, default: str | None = None) -> str | None:
    if key == CURRENT_ACTIVITY_SNAPSHOT:
        database_key = get_db_key()
        snapshot = get_runtime_activity_snapshot()
        if snapshot is None:
            _RAW_SNAPSHOT_FIXTURES.pop(database_key, None)
            return default if default is not None else ""
        raw = _RAW_SNAPSHOT_FIXTURES.get(database_key)
        if raw:
            try:
                if json.loads(raw) == snapshot:
                    return raw
            except json.JSONDecodeError:
                pass
        return json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"))
    if key == PENDING_SHORT_SECONDS:
        return "0"
    if key == PENDING_CARRY_PROVENANCE:
        return ""
    raise KeyError(f"unsupported runtime fixture key: {key}")
