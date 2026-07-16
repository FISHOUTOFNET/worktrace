from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_SERVICE = ROOT / "worktrace" / "services" / "runtime_activity_state_service.py"
SETTINGS_SERVICE = ROOT / "worktrace" / "services" / "settings_service.py"
SECURE_BACKUP = ROOT / "worktrace" / "services" / "secure_backup_service.py"
SNAPSHOT_PUBLISHER = ROOT / "worktrace" / "collector" / "snapshot_publisher.py"
FIXTURE = ROOT / "tests" / "support" / "runtime_state_fixture.py"
CONTRACT = ROOT / "tests" / "test_runtime_settings_cutover_contract.py"

RUNTIME_KEYS = frozenset(
    {
        "current_activity_snapshot",
        "pending_short_seconds",
        "pending_short_carry_provenance",
    }
)

RUNTIME_SERVICE_CONTENT = '''"""Process-local owner for transient current-activity display state.

Runtime activity state is deliberately kept out of SQLite. Durable activity
facts live in ``activity_log``; this module owns only one typed, display-safe
in-process sample namespaced by the configured database path.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass
import logging
import threading
from typing import Any, Iterator, Mapping

from ..db import get_db_key


@dataclass(frozen=True)
class RuntimeActivitySample:
    """One atomic, detached read of the current runtime activity state."""

    snapshot: dict[str, Any] | None
    revision: int


_LOCK = threading.RLock()
_SNAPSHOTS: dict[str, dict[str, Any] | None] = {}
_REVISIONS: dict[str, int] = {}
_BOUND_SAMPLE: ContextVar[tuple[str, RuntimeActivitySample] | None] = ContextVar(
    "worktrace_bound_runtime_activity_sample",
    default=None,
)


def _key(database_key: str | None = None) -> str:
    return str(database_key or get_db_key())


def _bump_locked(database_key: str) -> int:
    revision = int(_REVISIONS.get(database_key, 0)) + 1
    _REVISIONS[database_key] = revision
    return revision


@contextmanager
def bind_runtime_activity_sample(
    sample: RuntimeActivitySample,
    *,
    database_key: str | None = None,
) -> Iterator[None]:
    """Freeze one runtime sample for the duration of an explicit API request."""

    key = _key(database_key)
    detached = RuntimeActivitySample(
        snapshot=deepcopy(sample.snapshot) if sample.snapshot is not None else None,
        revision=int(sample.revision),
    )
    token = _BOUND_SAMPLE.set((key, detached))
    try:
        yield
    finally:
        _BOUND_SAMPLE.reset(token)


def publish_runtime_activity_snapshot(
    snapshot: Mapping[str, Any] | None,
    reason: str = "runtime_publish",
    *,
    database_key: str | None = None,
) -> int:
    """Publish a typed display-safe snapshot and return its local revision."""

    key = _key(database_key)
    detached = deepcopy(dict(snapshot)) if snapshot is not None else None
    with _LOCK:
        _SNAPSHOTS[key] = detached
        revision = _bump_locked(key)
    logging.debug(
        "runtime activity snapshot published reason=%s present=%s revision=%d",
        reason,
        detached is not None,
        revision,
    )
    return revision


def sample_runtime_activity_state(
    *, database_key: str | None = None
) -> RuntimeActivitySample:
    """Return one atomic detached sample for a page/API request."""

    key = _key(database_key)
    bound = _BOUND_SAMPLE.get()
    if bound is not None and bound[0] == key:
        sample = bound[1]
        return RuntimeActivitySample(
            snapshot=deepcopy(sample.snapshot) if sample.snapshot is not None else None,
            revision=int(sample.revision),
        )
    with _LOCK:
        snapshot = _SNAPSHOTS.get(key)
        return RuntimeActivitySample(
            snapshot=deepcopy(snapshot) if snapshot is not None else None,
            revision=int(_REVISIONS.get(key, 0)),
        )


def get_runtime_activity_snapshot(
    *, database_key: str | None = None
) -> dict[str, Any] | None:
    return sample_runtime_activity_state(database_key=database_key).snapshot


def clear_runtime_activity_state(
    reason: str,
    *,
    clear_snapshot: bool = True,
    clear_ownership: bool = True,
    database_key: str | None = None,
) -> None:
    """Clear transient state idempotently without touching durable history."""

    key = _key(database_key)
    changed = False
    with _LOCK:
        if clear_snapshot:
            changed = _SNAPSHOTS.get(key) is not None
            _SNAPSHOTS[key] = None
        if changed or clear_ownership:
            _bump_locked(key)
    logging.info(
        "runtime activity state cleared reason=%s snapshot=%s ownership=%s",
        reason,
        bool(clear_snapshot),
        bool(clear_ownership),
    )


def record_runtime_boundary(
    reason: str,
    *,
    clear_snapshot: bool = True,
) -> None:
    """Record a durable hard boundary and clear the process-local sample."""

    from . import session_boundary_service

    session_boundary_service.record_hard_boundary(reason=reason)
    clear_runtime_activity_state(
        reason,
        clear_snapshot=clear_snapshot,
        clear_ownership=True,
    )


__all__ = [
    "RuntimeActivitySample",
    "bind_runtime_activity_sample",
    "clear_runtime_activity_state",
    "get_runtime_activity_snapshot",
    "publish_runtime_activity_snapshot",
    "record_runtime_boundary",
    "sample_runtime_activity_state",
]
'''

SETTINGS_SERVICE_CONTENT = '''"""Durable application settings stored in SQLite."""

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


def _page_read_connection():
    # Imported lazily so ordinary settings and startup paths do not depend on
    # page-model modules. During a PageReadContext request this makes settings,
    # canonical projection and structural revision observe one SQLite snapshot.
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
    _SETTING_CACHE[(_settings_db_key(), key)] = (
        time.monotonic() + _SETTING_CACHE_TTL_SECONDS,
        value,
    )


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
'''

FIXTURE_CONTENT = '''"""Explicit test-only adapter for constructing typed runtime activity state."""

from __future__ import annotations

import json
from typing import Any

from worktrace.services.runtime_activity_state_service import (
    clear_runtime_activity_state,
    get_runtime_activity_snapshot,
    publish_runtime_activity_snapshot,
)

CURRENT_ACTIVITY_SNAPSHOT = "current_activity_snapshot"
PENDING_SHORT_SECONDS = "pending_short_seconds"
PENDING_CARRY_PROVENANCE = "pending_short_carry_provenance"


def set_setting(key: str, value: str) -> None:
    """Translate historical fixture vocabulary into the typed runtime owner."""

    if key == CURRENT_ACTIVITY_SNAPSHOT:
        raw = str(value or "")
        if not raw:
            clear_runtime_activity_state("test_fixture_clear")
            return
        try:
            parsed: Any = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError("runtime snapshot fixture must be valid JSON") from exc
        if not isinstance(parsed, dict):
            raise ValueError("runtime snapshot fixture must be a JSON object")
        publish_runtime_activity_snapshot(parsed, "test_fixture_publish")
        return
    if key in {PENDING_SHORT_SECONDS, PENDING_CARRY_PROVENANCE}:
        # Pending-short state was removed from production. Historical tests may
        # still seed it while migrating, but the effective value is always empty.
        return
    raise KeyError(f"unsupported runtime fixture key: {key}")


def get_setting(key: str, default: str | None = None) -> str | None:
    if key == CURRENT_ACTIVITY_SNAPSHOT:
        snapshot = get_runtime_activity_snapshot()
        if snapshot is None:
            return default if default is not None else ""
        return json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"))
    if key == PENDING_SHORT_SECONDS:
        return "0"
    if key == PENDING_CARRY_PROVENANCE:
        return ""
    raise KeyError(f"unsupported runtime fixture key: {key}")
'''

CONTRACT_CONTENT = '''"""Contracts for the typed runtime-state / durable-settings cutover."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = [pytest.mark.contract, pytest.mark.unit]
ROOT = Path(__file__).resolve().parents[1]
RUNTIME_KEYS = {
    "current_activity_snapshot",
    "pending_short_seconds",
    "pending_short_carry_provenance",
}
FORBIDDEN_RUNTIME_SYMBOLS = {
    "CURRENT_ACTIVITY_SNAPSHOT_KEY",
    "PENDING_SHORT_SECONDS_KEY",
    "PENDING_CARRY_PROVENANCE_KEY",
    "read_runtime_activity_snapshot_raw",
    "restore_runtime_activity_snapshot",
    "get_legacy_runtime_setting",
    "set_legacy_runtime_setting",
}


def _definitions(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }


def test_runtime_owner_has_no_raw_or_pending_compatibility_surface() -> None:
    path = ROOT / "worktrace" / "services" / "runtime_activity_state_service.py"
    source = path.read_text(encoding="utf-8")
    assert _definitions(path).isdisjoint(FORBIDDEN_RUNTIME_SYMBOLS)
    for value in FORBIDDEN_RUNTIME_SYMBOLS | RUNTIME_KEYS:
        assert value not in source


def test_settings_service_has_no_runtime_key_router() -> None:
    source = (
        ROOT / "worktrace" / "services" / "settings_service.py"
    ).read_text(encoding="utf-8")
    assert "_RUNTIME_ONLY_KEYS" not in source
    assert "runtime_activity_state_service" not in source
    for key in RUNTIME_KEYS:
        assert key not in source


def test_secure_backup_never_restores_pre_import_runtime_snapshot() -> None:
    source = (
        ROOT / "worktrace" / "services" / "secure_backup_service.py"
    ).read_text(encoding="utf-8")
    assert "restore_runtime_activity_snapshot" not in source
    assert "_snapshot_is_safe_to_restore" not in source
    assert "prior_snapshot" not in source


def _runtime_setting_calls(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    direct: dict[str, str] = {}
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module == "worktrace.services.settings_service":
                for item in node.names:
                    if item.name in {"get_setting", "set_setting"}:
                        direct[item.asname or item.name] = item.name
            elif node.module == "worktrace.services":
                for item in node.names:
                    if item.name == "settings_service":
                        modules.add(item.asname or item.name)
        elif isinstance(node, ast.Import):
            for item in node.names:
                if item.name == "worktrace.services.settings_service":
                    modules.add(item.asname or "settings_service")
    violations: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        name = None
        if isinstance(node.func, ast.Name):
            name = direct.get(node.func.id)
        elif (
            isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id in modules
            and node.func.attr in {"get_setting", "set_setting"}
        ):
            name = node.func.attr
        first = node.args[0]
        if (
            name is not None
            and isinstance(first, ast.Constant)
            and first.value in RUNTIME_KEYS
        ):
            violations.append(f"{path.relative_to(ROOT)}:{node.lineno}: {name}({first.value})")
    return violations


def test_production_and_tests_do_not_route_runtime_state_through_settings() -> None:
    violations: list[str] = []
    for root_name in ("worktrace", "tests"):
        for path in sorted((ROOT / root_name).rglob("*.py")):
            if path.name in {
                "runtime_state_fixture.py",
                "test_runtime_settings_cutover_contract.py",
            }:
                continue
            violations.extend(_runtime_setting_calls(path))
    assert not violations, "runtime settings calls remain:\n" + "\n".join(violations)
'''


def _remove_top_level_functions(source: str, names: set[str], path: Path) -> str:
    tree = ast.parse(source, filename=str(path))
    lines = source.splitlines(keepends=True)
    targets = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name in names
    ]
    found = {node.name for node in targets}
    missing = names - found
    if missing:
        raise RuntimeError(f"{path}: missing functions: {sorted(missing)}")
    for node in sorted(targets, key=lambda item: item.lineno, reverse=True):
        if node.end_lineno is None:
            raise RuntimeError(f"{path}:{node.name}: missing end line")
        start = node.lineno - 1
        while start > 0 and not lines[start - 1].strip():
            start -= 1
        del lines[start : node.end_lineno]
    return "".join(lines)


def _rewrite_secure_backup() -> None:
    source = SECURE_BACKUP.read_text(encoding="utf-8")
    source = source.replace(
        "from .runtime_activity_state_service import (\n"
        "    clear_runtime_activity_state,\n"
        "    restore_runtime_activity_snapshot,\n"
        ")\n",
        "from .runtime_activity_state_service import clear_runtime_activity_state\n",
        1,
    )
    source = source.replace(
        "_UNSAFE_SNAPSHOT_IDENTITY_KEYS = frozenset(\n"
        "    {\"id\", \"activity_id\", \"open_activity_id\", \"persisted_activity_id\"}\n"
        ")\n",
        "",
        1,
    )
    source = source.replace(
        "                prior_snapshot = get_setting(\"current_activity_snapshot\", \"\") or \"\"\n",
        "",
        1,
    )
    source = source.replace(
        "                        if _snapshot_is_safe_to_restore(prior_snapshot):\n"
        "                            restore_runtime_activity_snapshot(\n"
        "                                prior_snapshot,\n"
        "                                f\"{reason}_rollback\",\n"
        "                            )\n",
        "",
        1,
    )
    source = _remove_top_level_functions(
        source,
        {"_snapshot_is_safe_to_restore", "_contains_persisted_identity"},
        SECURE_BACKUP,
    )
    ast.parse(source, filename=str(SECURE_BACKUP))
    SECURE_BACKUP.write_text(source, encoding="utf-8")


def _settings_aliases(tree: ast.AST):
    direct: dict[str, str] = {}
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module == "worktrace.services.settings_service":
                for item in node.names:
                    if item.name in {"get_setting", "set_setting"}:
                        direct[item.asname or item.name] = item.name
            elif node.module == "worktrace.services":
                for item in node.names:
                    if item.name == "settings_service":
                        modules.add(item.asname or item.name)
        elif isinstance(node, ast.Import):
            for item in node.names:
                if item.name == "worktrace.services.settings_service":
                    modules.add(item.asname or "settings_service")
    return direct, modules


def _call_name(node: ast.Call, direct: dict[str, str], modules: set[str]) -> str | None:
    if isinstance(node.func, ast.Name):
        return direct.get(node.func.id)
    if (
        isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id in modules
        and node.func.attr in {"get_setting", "set_setting"}
    ):
        return node.func.attr
    return None


def _offsets(source: str) -> list[int]:
    offsets = [0]
    total = 0
    for line in source.splitlines(keepends=True):
        total += len(line)
        offsets.append(total)
    return offsets


def _rewrite_test_runtime_calls(path: Path) -> bool:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    direct, modules = _settings_aliases(tree)
    offsets = _offsets(source)
    replacements: list[tuple[int, int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        call_name = _call_name(node, direct, modules)
        first = node.args[0]
        if (
            call_name is None
            or not isinstance(first, ast.Constant)
            or first.value not in RUNTIME_KEYS
        ):
            continue
        func = node.func
        if func.end_lineno is None or func.end_col_offset is None:
            raise RuntimeError(f"{path}:{node.lineno}: function span unavailable")
        start = offsets[func.lineno - 1] + func.col_offset
        end = offsets[func.end_lineno - 1] + func.end_col_offset
        replacements.append((start, end, f"runtime_state_fixture.{call_name}"))
    if not replacements:
        return False
    for start, end, replacement in sorted(replacements, reverse=True):
        source = source[:start] + replacement + source[end:]
    if "from tests.support import runtime_state_fixture" not in source:
        migrated_tree = ast.parse(source, filename=str(path))
        insert_line = 0
        if (
            migrated_tree.body
            and isinstance(migrated_tree.body[0], ast.Expr)
            and isinstance(migrated_tree.body[0].value, ast.Constant)
            and isinstance(migrated_tree.body[0].value.value, str)
        ):
            insert_line = int(migrated_tree.body[0].end_lineno or 0)
        for node in migrated_tree.body:
            if isinstance(node, ast.ImportFrom) and node.module == "__future__":
                insert_line = max(insert_line, int(node.end_lineno or node.lineno))
        lines = source.splitlines(keepends=True)
        lines.insert(insert_line, "from tests.support import runtime_state_fixture\n")
        source = "".join(lines)
    ast.parse(source, filename=str(path))
    path.write_text(source, encoding="utf-8")
    return True


def main() -> int:
    RUNTIME_SERVICE.write_text(RUNTIME_SERVICE_CONTENT, encoding="utf-8")
    SETTINGS_SERVICE.write_text(SETTINGS_SERVICE_CONTENT, encoding="utf-8")
    _rewrite_secure_backup()

    publisher = SNAPSHOT_PUBLISHER.read_text(encoding="utf-8")
    publisher = publisher.replace("            clear_pending=False,\n", "", 1)
    ast.parse(publisher, filename=str(SNAPSHOT_PUBLISHER))
    SNAPSHOT_PUBLISHER.write_text(publisher, encoding="utf-8")

    FIXTURE.write_text(FIXTURE_CONTENT, encoding="utf-8")
    CONTRACT.write_text(CONTRACT_CONTENT, encoding="utf-8")

    migrated: list[str] = []
    for path in sorted((ROOT / "tests").rglob("*.py")):
        if path in {FIXTURE, CONTRACT}:
            continue
        if _rewrite_test_runtime_calls(path):
            migrated.append(path.relative_to(ROOT).as_posix())

    for path in (
        RUNTIME_SERVICE,
        SETTINGS_SERVICE,
        SECURE_BACKUP,
        SNAPSHOT_PUBLISHER,
        FIXTURE,
        CONTRACT,
    ):
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    print("Runtime/settings hard cutover prepared")
    print("Migrated test files:")
    print("\n".join(migrated))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
