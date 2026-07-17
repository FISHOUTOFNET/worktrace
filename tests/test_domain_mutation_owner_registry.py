from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.contract]

ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "domain_mutation_owners.json"
_WRITE_SQL_RE = re.compile(r"\b(?:INSERT\s+INTO|UPDATE\s+|DELETE\s+FROM|REPLACE\s+INTO)\b", re.IGNORECASE)


def _registry() -> dict:
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def test_active_database_boundary_has_no_business_sql_classifier() -> None:
    source = (ROOT / "worktrace/db.py").read_text(encoding="utf-8")
    forbidden = {
        "_classify_report_structure_sql",
        "_REPORT_STRUCTURE_TABLES",
        "ACTIVITY_PROJECT_ASSIGNMENT",
        "ACTIVITY_RESOURCE",
        "REPORT_SESSION_OPERATION",
    }
    assert not {token for token in forbidden if token in source}


def test_registered_facades_exist_and_declare_their_owner_kind() -> None:
    registry = _registry()
    for facade, metadata in registry["facades"].items():
        facade_path = ROOT / facade
        assert facade_path.is_file(), facade
        source = facade_path.read_text(encoding="utf-8")
        for marker in metadata["markers"]:
            assert marker in source, f"{facade}: missing {marker}"
        core = metadata.get("core")
        if core:
            core_path = ROOT / core
            assert core_path.is_file(), core
            assert core_path.stem in source, f"{facade}: core not routed"


def test_core_modules_are_imported_only_by_their_facades() -> None:
    registry = _registry()
    production = list((ROOT / "worktrace").rglob("*.py"))
    for facade, metadata in registry["facades"].items():
        core = metadata.get("core")
        if not core:
            continue
        token = Path(core).stem
        importers = {
            path.relative_to(ROOT).as_posix()
            for path in production
            if path.relative_to(ROOT).as_posix() != core
            and token in path.read_text(encoding="utf-8")
        }
        assert importers == {facade}, f"{token}: {sorted(importers)}"


def test_mutating_service_sql_is_core_or_low_level_repository() -> None:
    registry = _registry()
    facades = set(registry["facades"])
    cores = {
        metadata["core"]
        for metadata in registry["facades"].values()
        if metadata.get("core")
    }
    low_level = set(registry["low_level_repositories"])
    offenders: set[str] = set()
    for path in (ROOT / "worktrace/services").glob("*.py"):
        relative = path.relative_to(ROOT).as_posix()
        source = path.read_text(encoding="utf-8")
        if not _WRITE_SQL_RE.search(source):
            continue
        if relative in facades or relative in cores or relative in low_level:
            continue
        offenders.add(relative)
    assert offenders == set()
