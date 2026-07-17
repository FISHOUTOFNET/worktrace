from worktrace.constants import UNCATEGORIZED_PROJECT
from worktrace.services.project_snapshot_service import (
    serialize_project_snapshot,
    snapshot_from_activity_row,
)


def test_missing_assignment_maps_to_uncategorized_snapshot():
    snapshot = snapshot_from_activity_row({})

    assert snapshot.project_id is None
    assert snapshot.display_project_id is None
    assert snapshot.display_project_name == UNCATEGORIZED_PROJECT
    assert snapshot.is_uncategorized is True
    assert snapshot.is_suggested_project is False


def test_suggested_project_name_maps_to_display_only_snapshot():
    snapshot = snapshot_from_activity_row(
        {
            "project_id": 7,
            "project_name": UNCATEGORIZED_PROJECT,
            "project_enabled": 1,
            "assignment_source": "suggested_project_name",
            "suggested_project_name": "Matter Alpha",
            "assignment_confidence": 40,
        }
    )

    assert snapshot.project_id == 7
    assert snapshot.display_project_id is None
    assert snapshot.display_project_name == "Matter Alpha"
    assert snapshot.is_uncategorized is False
    assert snapshot.is_suggested_project is True


def test_disabled_project_maps_to_uncategorized_display_without_losing_raw_fact():
    snapshot = snapshot_from_activity_row(
        {
            "project_id": 42,
            "project_name": "Disabled Matter",
            "project_description": "hidden",
            "project_enabled": 0,
            "project_is_archived": 0,
            "project_is_deleted": 0,
            "assignment_source": "manual",
            "is_manual": 1,
        }
    )

    assert snapshot.project_id == 42
    assert snapshot.project_name == "Disabled Matter"
    assert snapshot.display_project_id is None
    assert snapshot.display_project_name == UNCATEGORIZED_PROJECT
    assert snapshot.is_uncategorized is True


def test_serialization_excludes_internal_lifecycle_fields():
    payload = serialize_project_snapshot(
        snapshot_from_activity_row(
            {
                "project_id": 9,
                "project_name": "Client",
                "project_description": "Matter",
                "project_enabled": 1,
                "assignment_source": "keyword_rule",
                "assignment_confidence": 80,
                "source_rule_type": "keyword",
                "source_rule_id": 13,
            }
        )
    )

    assert payload == {
        "id": 9,
        "name": "Client",
        "description": "Matter",
        "source": "keyword_rule",
        "is_manual": False,
        "confidence": 80,
        "suggested_project_name": "",
        "source_rule_type": "keyword",
        "source_rule_id": 13,
        "is_uncategorized": False,
        "is_suggested_project": False,
    }
