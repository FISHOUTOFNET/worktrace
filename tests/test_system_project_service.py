from __future__ import annotations

import sqlite3

import pytest

from worktrace.api import project_api, rule_api
from worktrace.constants import EXCLUDED_PROJECT, UNCATEGORIZED_PROJECT
from worktrace.db import get_connection
from worktrace.services import project_service, system_project_service


pytestmark = [pytest.mark.db, pytest.mark.contract]


def _delete_system_project(name: str) -> None:
    with get_connection() as conn:
        conn.execute("DELETE FROM project WHERE name = ?", (name,))


def test_normal_rule_api_requires_catalog_without_repairing_it(temp_db):
    _delete_system_project(EXCLUDED_PROJECT)

    result = rule_api.create_excluded_keyword_rule_for_webview("secret")

    assert result == {"ok": False, "error": "system_catalog_unavailable"}
    with get_connection() as conn:
        assert conn.execute(
            "SELECT id FROM project WHERE name = ?", (EXCLUDED_PROJECT,)
        ).fetchone() is None
        assert conn.execute("SELECT COUNT(*) FROM project_rule").fetchone()[0] == 0


def test_explicit_recovery_and_later_rule_creation_have_separate_transactions(temp_db):
    _delete_system_project(EXCLUDED_PROJECT)

    repaired = system_project_service.ensure_system_projects()
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id, created_by FROM project WHERE name = ?", (EXCLUDED_PROJECT,)
        ).fetchone()
        assert row is not None
        assert row["created_by"] == "system"
        assert conn.execute("SELECT COUNT(*) FROM project_rule").fetchone()[0] == 0

    result = rule_api.create_excluded_keyword_rule_for_webview("secret")
    assert result["ok"] is True
    assert result["rule"]["project_id"] == repaired["excluded"] == int(row["id"])


@pytest.mark.parametrize("reserved", [UNCATEGORIZED_PROJECT, EXCLUDED_PROJECT])
def test_user_project_cannot_claim_reserved_name_at_service_or_database_level(
    temp_db,
    reserved,
):
    with pytest.raises(ValueError, match="reserved_project_name"):
        project_service.create_project(reserved)
    assert project_api.create_project_for_rules(reserved) == {
        "ok": False,
        "error": "system_project",
    }
    with get_connection() as conn, pytest.raises(
        sqlite3.IntegrityError, match="reserved_project_name"
    ):
        conn.execute(
            """
            INSERT INTO project(
                name, description, language, is_archived, enabled,
                created_by, created_at, updated_at
            ) VALUES (?, '', '中文', 0, 1, 'user', ?, ?)
            """,
            (reserved, "2026-07-18 10:00:00", "2026-07-18 10:00:00"),
        )
