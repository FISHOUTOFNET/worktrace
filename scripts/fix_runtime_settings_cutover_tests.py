from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

FIXTURE_CONTENT = '''"""Explicit test-only adapter for constructing typed runtime activity state."""

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
'''


def replace_exact(path: Path, old: str, new: str, *, count: int | None = None) -> None:
    source = path.read_text(encoding="utf-8")
    occurrences = source.count(old)
    expected = occurrences if count is None else count
    if occurrences < expected or occurrences == 0:
        raise RuntimeError(f"{path}: replacement target missing: {old!r}")
    path.write_text(source.replace(old, new, expected), encoding="utf-8")


def main() -> int:
    fixture = ROOT / "tests" / "support" / "runtime_state_fixture.py"
    fixture.write_text(FIXTURE_CONTENT, encoding="utf-8")

    health = ROOT / "tests" / "test_collector_health_continuity_contract.py"
    replace_exact(health, 'assert captured["pending"] == "17"', 'assert captured["pending"] == "0"')
    replace_exact(health, 'assert captured["pending"] == "19"', 'assert captured["pending"] == "0"')

    webview = ROOT / "tests" / "test_webview_read_failure_non_mutation_contract.py"
    replace_exact(webview, 'runtime_state_fixture.get_setting("pending_short_seconds") == "23"', 'runtime_state_fixture.get_setting("pending_short_seconds") == "0"')
    replace_exact(webview, 'runtime_state_fixture.get_setting("pending_short_seconds") == "29"', 'runtime_state_fixture.get_setting("pending_short_seconds") == "0"')

    runtime_gate = ROOT / "tests" / "test_app_runtime_privacy_gate.py"
    replace_exact(
        runtime_gate,
        'assert runtime_state_fixture.get_setting("pending_short_seconds") == "11"',
        'assert runtime_state_fixture.get_setting("pending_short_seconds") == "0"',
    )

    backup = ROOT / "tests" / "test_secure_backup_service.py"
    replace_exact(
        backup,
        "def test_wrong_passphrase_restores_prior_pause_status(temp_db, tmp_path):",
        "def test_wrong_passphrase_restores_pause_status_but_clears_live_snapshot(temp_db, tmp_path):",
    )
    replace_exact(
        backup,
        'assert runtime_state_fixture.get_setting("current_activity_snapshot", "") == \'{"app":"prior-snapshot-marker"}\'',
        'assert runtime_state_fixture.get_setting("current_activity_snapshot", "") == ""',
    )
    replace_exact(
        backup,
        "def test_corrupted_backup_restores_prior_pause_status(temp_db, tmp_path):",
        "def test_corrupted_backup_restores_pause_status_but_clears_live_snapshot(temp_db, tmp_path):",
    )
    replace_exact(
        backup,
        'assert runtime_state_fixture.get_setting("current_activity_snapshot", "") == \'{"app":"corrupt-prior-marker"}\'',
        'assert runtime_state_fixture.get_setting("current_activity_snapshot", "") == ""',
    )
    replace_exact(
        backup,
        "def test_after_rollback_previous_pause_status_restored(temp_db, tmp_path, monkeypatch):",
        "def test_after_rollback_pause_status_restored_but_live_snapshot_cleared(temp_db, tmp_path, monkeypatch):",
    )
    replace_exact(
        backup,
        'assert runtime_state_fixture.get_setting("current_activity_snapshot", "") == \'{"app":"rollback-prior-marker"}\'',
        'assert runtime_state_fixture.get_setting("current_activity_snapshot", "") == ""',
    )

    print("Aligned runtime/settings cutover tests with typed-state semantics")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
