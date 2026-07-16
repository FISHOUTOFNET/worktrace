from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tests.support import activity_factory

pytestmark = [pytest.mark.db, pytest.mark.contract]


def test_activity_fixture_builds_raw_fact_without_production_lifecycle(temp_db):
    activity_id = activity_factory.create_activity(
        "Word",
        "winword.exe",
        "Fixture.docx",
        start_time="2026-06-18 09:00:00",
    )
    activity_factory.set_activity_duration(activity_id, 60)
    activity_factory.close_activity(activity_id, "2026-06-18 09:01:00")

    row = activity_factory.get_activity(activity_id)
    assert row["start_time"] == "2026-06-18 09:00:00"
    assert row["end_time"] == "2026-06-18 09:01:00"
    assert row["duration_seconds"] == 60


def test_activity_fixture_write_methods_use_repository_not_query_service():
    path = Path(activity_factory.__file__)
    tree = ast.parse(path.read_text(encoding="utf-8"))
    forbidden = {
        "create_activity",
        "insert_activity_row",
        "close_activity",
        "close_activity_row",
        "close_all_open_rows",
        "set_activity_duration",
        "increment_activity_duration",
        "reopen_activity",
        "finalize_created_activity",
        "apply_midnight_anchor_assignment",
    }
    violations: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        target = node.func
        if (
            isinstance(target, ast.Attribute)
            and isinstance(target.value, ast.Name)
            and target.value.id == "_activity_queries"
            and target.attr in forbidden
        ):
            violations.append(target.attr)
    assert violations == []


def test_production_package_does_not_import_test_activity_facade():
    root = Path(__file__).resolve().parents[1] / "worktrace"
    violations: list[str] = []
    for path in root.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        if "tests.support.activity_factory" in source:
            violations.append(str(path.relative_to(root)))
    assert violations == []
