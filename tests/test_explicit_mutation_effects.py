from __future__ import annotations

import pytest

from tests.support import activity_factory as activity_service
from worktrace.db import get_connection, now_str
from worktrace.mutation_effects import MutationEffect, mutation_effects
from worktrace.services import project_service

pytestmark = [pytest.mark.db, pytest.mark.integration, pytest.mark.contract]

DATE = "2026-07-17"


def _generation() -> int:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT generation FROM report_structure_revision_state WHERE singleton_id = 1"
        ).fetchone()
    assert row is not None
    return int(row["generation"])


def _activity() -> int:
    return activity_service.create_activity(
        "Word",
        "winword.exe",
        "Effects.docx - Word",
        start_time=f"{DATE} 09:00:00",
    )


def test_unscoped_sql_has_no_domain_effect(temp_db):
    activity_id = _activity()
    before = _generation()

    with get_connection() as conn:
        conn.execute(
            "UPDATE activity_log SET status = ?, updated_at = ? WHERE id = ?",
            ("idle", now_str(), activity_id),
        )

    assert _generation() == before


def test_explicit_effect_is_persisted_once_per_transaction(temp_db):
    activity_id = _activity()
    before = _generation()

    with mutation_effects(MutationEffect.REPORT_STRUCTURE):
        with get_connection() as conn:
            conn.execute(
                "UPDATE activity_log SET status = ?, updated_at = ? WHERE id = ?",
                ("idle", now_str(), activity_id),
            )
            conn.execute(
                "UPDATE activity_log SET source = ?, updated_at = ? WHERE id = ?",
                ("manual", now_str(), activity_id),
            )

    assert _generation() == before + 1


def test_rollback_discards_explicit_effect(temp_db):
    activity_id = _activity()
    before = _generation()

    with mutation_effects(MutationEffect.REPORT_STRUCTURE):
        conn = get_connection()
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "UPDATE activity_log SET status = ?, updated_at = ? WHERE id = ?",
                ("idle", now_str(), activity_id),
            )
            conn.rollback()
        finally:
            conn.close()

    assert _generation() == before


def test_domain_owner_declares_effect_without_database_sql_knowledge(temp_db):
    before = _generation()

    project_service.create_project("Explicit Effect Project")

    assert _generation() == before + 1
