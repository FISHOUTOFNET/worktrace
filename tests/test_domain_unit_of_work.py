from __future__ import annotations

import pytest

from worktrace.data_generation_repository import (
    DataGenerationNamespace,
    DataGenerationRepository,
)
from worktrace.db import get_connection
from worktrace.domain_unit_of_work import DomainUnitOfWork
from worktrace.services import activity_lifecycle_service

pytestmark = [
    pytest.mark.db,
    pytest.mark.integration,
    pytest.mark.contract,
    pytest.mark.serial,
]


def _generation(namespace: DataGenerationNamespace) -> int:
    with get_connection() as conn:
        return DataGenerationRepository.get(conn, namespace)


def test_deeply_nested_unit_of_work_commits_data_and_effect_once(temp_db):
    before = _generation(DataGenerationNamespace.REPORT_STRUCTURE)

    with DomainUnitOfWork((DataGenerationNamespace.REPORT_STRUCTURE,)) as outer:
        outer.connection.execute(
            "INSERT INTO session_boundary(occurred_at, reason, created_at) "
            "VALUES (?, ?, ?)",
            ("2026-07-17 09:00:00", "test", "2026-07-17 09:00:00"),
        )
        outer.mark_changed()
        with DomainUnitOfWork((DataGenerationNamespace.REPORT_STRUCTURE,)) as middle:
            assert middle.connection is outer.connection
            with DomainUnitOfWork((DataGenerationNamespace.REPORT_STRUCTURE,)) as inner:
                assert inner.connection is outer.connection
                inner.mark_changed()

    assert _generation(DataGenerationNamespace.REPORT_STRUCTURE) == before + 1


def test_nested_failure_marks_root_transaction_rollback_only(temp_db):
    before = _generation(DataGenerationNamespace.REPORT_STRUCTURE)

    with DomainUnitOfWork((DataGenerationNamespace.REPORT_STRUCTURE,)) as outer:
        outer.connection.execute(
            "INSERT INTO session_boundary(occurred_at, reason, created_at) "
            "VALUES (?, ?, ?)",
            ("2026-07-17 10:00:00", "rollback", "2026-07-17 10:00:00"),
        )
        outer.mark_changed()
        try:
            with DomainUnitOfWork() as inner:
                assert inner.connection is outer.connection
                raise RuntimeError("rollback-contract")
        except RuntimeError as exc:
            assert str(exc) == "rollback-contract"

    assert _generation(DataGenerationNamespace.REPORT_STRUCTURE) == before
    with get_connection() as conn:
        assert conn.execute(
            "SELECT 1 FROM session_boundary WHERE reason = ?",
            ("rollback",),
        ).fetchone() is None


def test_non_report_effect_is_published_explicitly(temp_db):
    settings_before = _generation(DataGenerationNamespace.SETTINGS)
    report_before = _generation(DataGenerationNamespace.REPORT_STRUCTURE)

    with DomainUnitOfWork((DataGenerationNamespace.SETTINGS,)) as uow:
        uow.connection.execute(
            """
            INSERT INTO settings(key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_at = excluded.updated_at
            """,
            ("ui_refresh_seconds", "77", "2026-07-17 10:30:00"),
        )
        uow.mark_changed()

    assert _generation(DataGenerationNamespace.SETTINGS) == settings_before + 1
    assert _generation(DataGenerationNamespace.REPORT_STRUCTURE) == report_before


def test_activity_checkpoint_does_not_publish_structure_generation(temp_db):
    activity_id = activity_lifecycle_service.persist_open_activity(
        start_time="2026-07-17 11:00:00",
        source="auto",
        payload={
            "status": "normal",
            "app_name": "Word",
            "process_name": "winword.exe",
            "window_title": "UoW.docx",
        },
    )
    before = _generation(DataGenerationNamespace.REPORT_STRUCTURE)

    assert activity_lifecycle_service.checkpoint_activity(activity_id, 30) is True
    assert _generation(DataGenerationNamespace.REPORT_STRUCTURE) == before


def test_no_op_close_does_not_publish_structure_generation(temp_db):
    activity_id = activity_lifecycle_service.persist_open_activity(
        start_time="2026-07-17 12:00:00",
        source="auto",
        payload={
            "status": "normal",
            "app_name": "Word",
            "process_name": "winword.exe",
            "window_title": "NoOp.docx",
        },
    )
    activity_lifecycle_service.close_activity(activity_id, "2026-07-17 12:10:00")
    before = _generation(DataGenerationNamespace.REPORT_STRUCTURE)

    activity_lifecycle_service.close_activity(activity_id, "2026-07-17 12:10:00")

    assert _generation(DataGenerationNamespace.REPORT_STRUCTURE) == before


def test_nested_no_op_inner_does_not_bump_unrelated_namespace(temp_db):
    """Outer modifies REPORT_STRUCTURE; inner declares SETTINGS but is no-op.

    Only REPORT_STRUCTURE should be bumped; SETTINGS must stay unchanged.
    """

    report_before = _generation(DataGenerationNamespace.REPORT_STRUCTURE)
    settings_before = _generation(DataGenerationNamespace.SETTINGS)

    with DomainUnitOfWork((DataGenerationNamespace.REPORT_STRUCTURE,)) as outer:
        outer.connection.execute(
            "INSERT INTO session_boundary(occurred_at, reason, created_at) "
            "VALUES (?, ?, ?)",
            ("2026-07-17 13:00:00", "outer-write", "2026-07-17 13:00:00"),
        )
        outer.mark_changed(DataGenerationNamespace.REPORT_STRUCTURE)
        with DomainUnitOfWork((DataGenerationNamespace.SETTINGS,)) as inner:
            assert inner.connection is outer.connection
            # inner declares SETTINGS but performs no writes and no mark_changed

    assert _generation(DataGenerationNamespace.REPORT_STRUCTURE) == report_before + 1
    assert _generation(DataGenerationNamespace.SETTINGS) == settings_before


def test_nested_no_op_outer_does_not_bump_unrelated_namespace(temp_db):
    """Outer declares REPORT_STRUCTURE but is no-op; inner modifies SETTINGS.

    Only SETTINGS should be bumped; REPORT_STRUCTURE must stay unchanged.
    """

    report_before = _generation(DataGenerationNamespace.REPORT_STRUCTURE)
    settings_before = _generation(DataGenerationNamespace.SETTINGS)

    with DomainUnitOfWork((DataGenerationNamespace.REPORT_STRUCTURE,)) as outer:
        with DomainUnitOfWork((DataGenerationNamespace.SETTINGS,)) as inner:
            assert inner.connection is outer.connection
            inner.connection.execute(
                """
                INSERT INTO settings(key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = excluded.updated_at
                """,
                ("nested_inner_key", "1", "2026-07-17 14:00:00"),
            )
            inner.mark_changed(DataGenerationNamespace.SETTINGS)

    assert _generation(DataGenerationNamespace.REPORT_STRUCTURE) == report_before
    assert _generation(DataGenerationNamespace.SETTINGS) == settings_before + 1


def test_nested_different_namespaces_each_bump_once(temp_db):
    """Outer modifies REPORT_STRUCTURE; inner modifies SETTINGS.

    Each namespace should bump exactly once.
    """

    report_before = _generation(DataGenerationNamespace.REPORT_STRUCTURE)
    settings_before = _generation(DataGenerationNamespace.SETTINGS)

    with DomainUnitOfWork((DataGenerationNamespace.REPORT_STRUCTURE,)) as outer:
        outer.connection.execute(
            "INSERT INTO session_boundary(occurred_at, reason, created_at) "
            "VALUES (?, ?, ?)",
            ("2026-07-17 15:00:00", "both-outer", "2026-07-17 15:00:00"),
        )
        outer.mark_changed(DataGenerationNamespace.REPORT_STRUCTURE)
        with DomainUnitOfWork((DataGenerationNamespace.SETTINGS,)) as inner:
            inner.connection.execute(
                """
                INSERT INTO settings(key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = excluded.updated_at
                """,
                ("both_inner_key", "2", "2026-07-17 15:00:00"),
            )
            inner.mark_changed(DataGenerationNamespace.SETTINGS)

    assert _generation(DataGenerationNamespace.REPORT_STRUCTURE) == report_before + 1
    assert _generation(DataGenerationNamespace.SETTINGS) == settings_before + 1


def test_same_namespace_multi_layer_bumps_once(temp_db):
    """Outer and inner both mark REPORT_STRUCTURE; it should bump only once."""

    before = _generation(DataGenerationNamespace.REPORT_STRUCTURE)

    with DomainUnitOfWork((DataGenerationNamespace.REPORT_STRUCTURE,)) as outer:
        outer.connection.execute(
            "INSERT INTO session_boundary(occurred_at, reason, created_at) "
            "VALUES (?, ?, ?)",
            ("2026-07-17 16:00:00", "multi-outer", "2026-07-17 16:00:00"),
        )
        outer.mark_changed(DataGenerationNamespace.REPORT_STRUCTURE)
        with DomainUnitOfWork((DataGenerationNamespace.REPORT_STRUCTURE,)) as inner:
            inner.connection.execute(
                "INSERT INTO session_boundary(occurred_at, reason, created_at) "
                "VALUES (?, ?, ?)",
                ("2026-07-17 16:01:00", "multi-inner", "2026-07-17 16:01:00"),
            )
            inner.mark_changed(DataGenerationNamespace.REPORT_STRUCTURE)

    assert _generation(DataGenerationNamespace.REPORT_STRUCTURE) == before + 1


def test_inner_exception_rolls_back_all_generations(temp_db):
    """Inner raises; root must roll back data and all generations."""

    report_before = _generation(DataGenerationNamespace.REPORT_STRUCTURE)
    settings_before = _generation(DataGenerationNamespace.SETTINGS)

    with pytest.raises(RuntimeError, match="inner-failure"):
        with DomainUnitOfWork((DataGenerationNamespace.REPORT_STRUCTURE,)) as outer:
            outer.connection.execute(
                "INSERT INTO session_boundary(occurred_at, reason, created_at) "
                "VALUES (?, ?, ?)",
                ("2026-07-17 17:00:00", "rollback-outer", "2026-07-17 17:00:00"),
            )
            outer.mark_changed(DataGenerationNamespace.REPORT_STRUCTURE)
            with DomainUnitOfWork((DataGenerationNamespace.SETTINGS,)) as inner:
                inner.connection.execute(
                    """
                    INSERT INTO settings(key, value, updated_at)
                    VALUES (?, ?, ?)
                    """,
                    ("rollback_inner", "3", "2026-07-17 17:00:00"),
                )
                inner.mark_changed(DataGenerationNamespace.SETTINGS)
                raise RuntimeError("inner-failure")

    assert _generation(DataGenerationNamespace.REPORT_STRUCTURE) == report_before
    assert _generation(DataGenerationNamespace.SETTINGS) == settings_before
    with get_connection() as conn:
        assert conn.execute(
            "SELECT 1 FROM session_boundary WHERE reason = ?",
            ("rollback-outer",),
        ).fetchone() is None
        assert conn.execute(
            "SELECT 1 FROM settings WHERE key = ?",
            ("rollback_inner",),
        ).fetchone() is None


def test_declared_effect_without_mark_changed_publishes_nothing(temp_db):
    """A scope that declares an effect but never marks it must not publish."""

    report_before = _generation(DataGenerationNamespace.REPORT_STRUCTURE)
    settings_before = _generation(DataGenerationNamespace.SETTINGS)

    with DomainUnitOfWork(
        (
            DataGenerationNamespace.REPORT_STRUCTURE,
            DataGenerationNamespace.SETTINGS,
        )
    ) as uow:
        uow.connection.execute(
            "INSERT INTO session_boundary(occurred_at, reason, created_at) "
            "VALUES (?, ?, ?)",
            ("2026-07-17 18:00:00", "declare-only", "2026-07-17 18:00:00"),
        )
        # Deliberately do NOT call mark_changed for either namespace

    assert _generation(DataGenerationNamespace.REPORT_STRUCTURE) == report_before
    assert _generation(DataGenerationNamespace.SETTINGS) == settings_before
