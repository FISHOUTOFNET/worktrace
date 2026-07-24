from __future__ import annotations

import pytest

from tests.support import activity_factory as activity_service
from worktrace.data_generation_repository import DataGenerationNamespace
from worktrace.db import get_connection, now_str
from worktrace.domain_unit_of_work import DomainUnitOfWork
from worktrace.resources.types import DetectedResource
from worktrace.services import (
    database_maintenance_service,
    report_revision_service,
    resource_service,
)
from worktrace.services.settings_service import set_setting

pytestmark = [pytest.mark.db, pytest.mark.integration, pytest.mark.contract]
DATE = "2026-07-15"


def _open_activity() -> int:
    return activity_service.create_activity(
        "Word",
        "winword.exe",
        "Generation.docx - Word",
        start_time=f"{DATE} 09:00:00",
        file_path_hint="D:\\Generation\\Generation.docx",
    )


def test_heartbeat_revision_reuses_token_until_structural_commit(temp_db):
    """The source-version token is stable until REPORT_STRUCTURE bumps."""

    activity_id = _open_activity()
    report_revision_service.clear_report_structure_revision_cache()

    first = report_revision_service.get_report_structure_revision(DATE)
    assert report_revision_service.get_report_structure_revision(DATE) == first

    # Non-structural changes (raw UPDATE without UoW) do not bump the
    # generation, so the source-version token stays the same.
    with get_connection() as conn:
        conn.execute(
            "UPDATE activity_log SET duration_seconds = ?, updated_at = ? WHERE id = ?",
            (777, now_str(), activity_id),
        )
    set_setting("collector_status", "running")
    assert report_revision_service.get_report_structure_revision(DATE) == first

    # Rolled-back UoW does not bump the generation.
    with DomainUnitOfWork((DataGenerationNamespace.REPORT_STRUCTURE,)) as uow:
        uow.connection.execute(
            "UPDATE activity_log SET status = ?, updated_at = ? WHERE id = ?",
            ("idle", now_str(), activity_id),
        )
        uow.mark_changed(DataGenerationNamespace.REPORT_STRUCTURE)
        uow.mark_rollback_only()
    assert report_revision_service.get_report_structure_revision(DATE) == first

    # Committed UoW bumps REPORT_STRUCTURE, so the token changes.
    with DomainUnitOfWork((DataGenerationNamespace.REPORT_STRUCTURE,)) as uow:
        uow.connection.execute(
            "UPDATE activity_log SET status = ?, updated_at = ? WHERE id = ?",
            ("idle", now_str(), activity_id),
        )
        uow.mark_changed(DataGenerationNamespace.REPORT_STRUCTURE)
    changed = report_revision_service.get_report_structure_revision(DATE)
    assert changed != first


def test_structural_setting_commit_invalidates_cached_revision(temp_db):
    _open_activity()
    report_revision_service.clear_report_structure_revision_cache()
    first = report_revision_service.get_report_structure_revision(DATE)

    set_setting("context_carry_minutes", "7")

    second = report_revision_service.get_report_structure_revision(DATE)
    assert second != first


def test_database_replacement_invalidates_cached_revision(temp_db):
    _open_activity()
    report_revision_service.clear_report_structure_revision_cache()

    first = report_revision_service.get_report_structure_revision(DATE)

    database_maintenance_service.clear_all_live_data()

    second = report_revision_service.get_report_structure_revision(DATE)
    assert second != first


def test_unchanged_resource_upsert_does_not_invalidate_revision(temp_db):
    activity_id = _open_activity()
    stored = resource_service.get_resource_for_activity(activity_id)
    assert stored is not None
    resource = DetectedResource(
        resource_kind=str(stored["resource_kind"]),
        resource_subtype=str(stored["resource_subtype"]),
        display_name=str(stored["display_name"]),
        identity_key=str(stored["identity_key"]),
        is_anchor=bool(stored["is_anchor"]),
        confidence=int(stored["confidence"]),
        source=str(stored["source"]),
        app_name=str(stored["app_name"]),
        process_name=str(stored["process_name"]),
        window_title=str(stored["window_title"]),
        path_hint=stored.get("path_hint"),
        uri_scheme=stored.get("uri_scheme"),
        uri_host=stored.get("uri_host"),
        uri_hint=stored.get("uri_hint"),
        metadata_json=stored.get("metadata_json"),
    )
    report_revision_service.clear_report_structure_revision_cache()

    first = report_revision_service.get_report_structure_revision(DATE)
    resource_service.create_or_update_activity_resource(activity_id, resource)
    second = report_revision_service.get_report_structure_revision(DATE)

    assert second == first
