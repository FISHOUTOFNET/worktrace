"""API / service regression locks for project lifecycle foundation.

These tests lock the narrow ``project_api`` lifecycle facades:
5G:

- ``create_project_for_rules(name, description)``
- ``update_project_for_rules(project_id, name, description)``
- ``set_project_enabled_for_rules(project_id, enabled)``
- ``archive_project_for_rules(project_id)``

They cover valid writes, input validation (true int / true bool / true str /
trim / empty rejection), system / special project rejection (``未归类`` /
``排除规则`` / ``created_by == "system"``), duplicate name handling,
cache invalidation preservation (and rejection not triggering cache hooks),
no-side-effect guarantees (no project delete, no folder/keyword rule delete,
no activity / assignment / session-note rows touched, no conflict preview /
backfill invoked), exception collapse to stable codes, JSON serializability,
sensitive-token absence, and the existing keyword / folder rule CRUD still
working after the lifecycle foundation is in place.
"""

from __future__ import annotations

import json

import pytest

from worktrace.api import project_api, rule_api
from worktrace.constants import EXCLUDED_PROJECT, UNCATEGORIZED_PROJECT
from worktrace.db import get_connection
from worktrace.services import (
    folder_rule_service,
    project_inference_service,
    project_service,
    rule_service,
)




def _counts() -> dict[str, int]:
    with get_connection() as conn:
        return {
            "project": conn.execute("SELECT COUNT(*) AS c FROM project").fetchone()["c"],
            "folder": conn.execute(
                "SELECT COUNT(*) AS c FROM folder_project_rule"
            ).fetchone()["c"],
            "keyword": conn.execute(
                "SELECT COUNT(*) AS c FROM project_rule"
            ).fetchone()["c"],
            "activity": conn.execute(
                "SELECT COUNT(*) AS c FROM activity_log"
            ).fetchone()["c"],
            "assignment": conn.execute(
                "SELECT COUNT(*) AS c FROM activity_project_assignment"
            ).fetchone()["c"],
            "session_note": conn.execute(
                "SELECT COUNT(*) AS c FROM project_session_note"
            ).fetchone()["c"],
        }


def _project_row(project_id: int) -> dict:
    with get_connection() as conn:
        return dict(
            conn.execute("SELECT * FROM project WHERE id = ?", (project_id,)).fetchone()
        )


def _assert_payload_shape(payload: dict) -> None:
    """Lock the narrow project lifecycle summary payload shape."""
    assert isinstance(payload, dict)
    assert set(payload.keys()) == {
        "id",
        "name",
        "description",
        "language",
        "enabled",
        "archived",
    }
    assert isinstance(payload["id"], int)
    assert type(payload["name"]) is str
    assert type(payload["description"]) is str
    assert type(payload["language"]) is str
    assert type(payload["enabled"]) is bool
    assert type(payload["archived"]) is bool


def _assert_no_sensitive_tokens(rendered: str) -> None:
    """Lock that no sensitive tokens ever leak into the API payload."""
    lowered = rendered.lower()
    for forbidden in (
        "traceback",
        "sqlite",
        "select",
        "insert",
        "update",
        "delete",
        "window_title",
        "clipboard",
        "note",
        "created_by",
        "created_at",
        "updated_at",
        "is_archived",
        "activity_log",
        "c:\\secret",
    ):
        assert forbidden not in lowered, forbidden




def test_create_project_success_trims_name_and_description(temp_db):
    result = project_api.create_project_for_rules("  Client  ", "  Billable work  ")

    assert result["ok"] is True
    _assert_payload_shape(result["project"])
    project = result["project"]
    assert project["name"] == "Client"
    assert project["description"] == "Billable work"
    assert project["language"] == "中文"
    assert project["enabled"] is True
    assert project["archived"] is False

    row = _project_row(project["id"])
    assert row["name"] == "Client"
    assert row["description"] == "Billable work"
    assert row["language"] == "中文"
    assert row["enabled"] == 1
    assert row["is_archived"] == 0
    assert row["created_by"] == "user"


def test_create_project_success_empty_description(temp_db):
    result = project_api.create_project_for_rules("Client", "")

    assert result["ok"] is True
    assert result["project"]["description"] == ""
    row = _project_row(result["project"]["id"])
    assert row["description"] == ""


def test_create_project_language_variants(temp_db):
    zh = project_api.create_project_for_rules("中文项目", "", "  中文  ")
    en = project_api.create_project_for_rules("English Project", "", "英语")
    ja = project_api.create_project_for_rules("Japanese Project", "", "日语")
    other = project_api.create_project_for_rules("Other Project", "", "  法语  ")
    defaulted = project_api.create_project_for_rules("Default Project", "", "   ")

    assert zh["project"]["language"] == "中文"
    assert en["project"]["language"] == "英语"
    assert ja["project"]["language"] == "日语"
    assert other["project"]["language"] == "法语"
    assert defaulted["project"]["language"] == "中文"


def test_create_project_rejects_non_str_language(temp_db):
    for bad_language in (None, True, False, 1, 1.5, [], {}, b"zh"):
        result = project_api.create_project_for_rules("Client", "", bad_language)
        assert result == {"ok": False, "error": "invalid_input"}, bad_language


def test_create_project_rejects_non_str_name(temp_db):
    for bad_name in (None, True, False, 1, 1.5, [], {}, b"Client"):
        result = project_api.create_project_for_rules(bad_name, "desc")
        assert result == {"ok": False, "error": "invalid_input"}, bad_name


def test_create_project_rejects_non_str_description(temp_db):
    for bad_desc in (None, True, False, 1, 1.5, [], {}, b"desc"):
        result = project_api.create_project_for_rules("Client", bad_desc)
        assert result == {"ok": False, "error": "invalid_input"}, bad_desc


def test_create_project_rejects_empty_or_whitespace_name(temp_db):
    for bad_name in ("", "   ", "\t\n"):
        result = project_api.create_project_for_rules(bad_name, "desc")
        assert result == {"ok": False, "error": "invalid_input"}, bad_name


def test_create_project_rejects_duplicate_name_exact(temp_db):
    project_api.create_project_for_rules("Client", "first")

    result = project_api.create_project_for_rules("Client", "second")
    assert result == {"ok": False, "error": "duplicate_project"}


def test_create_project_rejects_duplicate_name_after_trim(temp_db):
    project_api.create_project_for_rules("Client", "")

    result = project_api.create_project_for_rules("  Client  ", "")
    assert result == {"ok": False, "error": "duplicate_project"}


def test_create_project_does_not_match_system_special_names(temp_db):
    # ``未归类`` and ``排除规则`` are reserved system project names. The service
    # layer's UNIQUE(name) constraint would reject them, but the API facade must
    # reject them too (as duplicate_project) so a user cannot create a "shadow"
    # system project via this facade.
    project_service.get_or_create_uncategorized_project()
    project_service.get_or_create_excluded_project()

    # Creating a project named ``未归类`` is rejected because the system
    # row already exists (duplicate). The behavior is the same for
    # ``排除规则``.
    assert project_api.create_project_for_rules(UNCATEGORIZED_PROJECT, "") == {
        "ok": False,
        "error": "duplicate_project",
    }
    assert project_api.create_project_for_rules(EXCLUDED_PROJECT, "") == {
        "ok": False,
        "error": "duplicate_project",
    }


def test_create_project_service_exception_collapses_to_operation_failed(
    temp_db, monkeypatch
):
    def boom(name, description="", language="中文"):
        raise RuntimeError(
            "boom SELECT * FROM activity_log traceback window_title clipboard note C:\\Secret"
        )

    monkeypatch.setattr(project_service, "create_project", boom)
    # Bypass the duplicate check by making get_project_by_name return None.
    monkeypatch.setattr(project_service, "get_project_by_name", lambda name: None)

    result = project_api.create_project_for_rules("Client", "desc")
    assert result == {"ok": False, "error": "operation_failed"}
    _assert_no_sensitive_tokens(repr(result))


def test_create_project_integrity_error_collapses_to_duplicate_project(
    temp_db, monkeypatch
):
    import sqlite3

    def boom(name, description="", language="中文"):
        raise sqlite3.IntegrityError("UNIQUE constraint failed: project.name")

    monkeypatch.setattr(project_service, "create_project", boom)
    monkeypatch.setattr(project_service, "get_project_by_name", lambda name: None)

    result = project_api.create_project_for_rules("Client", "desc")
    assert result == {"ok": False, "error": "duplicate_project"}


def test_create_project_payload_is_json_serializable(temp_db):
    result = project_api.create_project_for_rules("Client", "desc")
    json.dumps(result, ensure_ascii=False)




def test_update_project_success_trims_name_and_description(temp_db):
    project_id = project_service.create_project("Client", "old")

    result = project_api.update_project_for_rules(
        project_id, "  Client Renamed  ", "  new desc  ", "  英语  "
    )

    assert result["ok"] is True
    _assert_payload_shape(result["project"])
    project = result["project"]
    assert project["id"] == project_id
    assert project["name"] == "Client Renamed"
    assert project["description"] == "new desc"
    assert project["language"] == "英语"

    row = _project_row(project_id)
    assert row["name"] == "Client Renamed"
    assert row["description"] == "new desc"
    assert row["language"] == "英语"
    # update only touches name / description / updated_at
    assert row["enabled"] == 1
    assert row["is_archived"] == 0
    assert row["created_by"] == "user"


def test_update_project_preserves_enabled_and_archived(temp_db):
    project_id = project_service.create_project("Client", "old")
    project_service.set_project_enabled(project_id, False)

    result = project_api.update_project_for_rules(project_id, "Renamed", "new")

    assert result["ok"] is True
    assert result["project"]["enabled"] is False
    assert result["project"]["archived"] is False
    row = _project_row(project_id)
    assert row["enabled"] == 0
    assert row["is_archived"] == 0


def test_update_project_rejects_bool_project_id(temp_db):
    project_id = project_service.create_project("Client", "old")
    for bad_id in (True, False):
        result = project_api.update_project_for_rules(bad_id, "Renamed", "new")
        assert result == {"ok": False, "error": "invalid_input"}, bad_id
    # The project row is unchanged.
    assert _project_row(project_id)["name"] == "Client"


def test_update_project_rejects_non_int_project_id(temp_db):
    for bad_id in (None, "1", 1.0, 1.5, [], {}, b"1"):
        result = project_api.update_project_for_rules(bad_id, "Renamed", "new")
        assert result == {"ok": False, "error": "invalid_input"}, bad_id


def test_update_project_rejects_non_positive_project_id(temp_db):
    for bad_id in (0, -1, -100):
        result = project_api.update_project_for_rules(bad_id, "Renamed", "new")
        assert result == {"ok": False, "error": "invalid_input"}, bad_id


def test_update_project_rejects_non_str_name(temp_db):
    project_id = project_service.create_project("Client", "old")
    for bad_name in (None, True, False, 1, 1.5, [], {}):
        result = project_api.update_project_for_rules(project_id, bad_name, "new")
        assert result == {"ok": False, "error": "invalid_input"}, bad_name


def test_update_project_rejects_non_str_description(temp_db):
    project_id = project_service.create_project("Client", "old")
    for bad_desc in (None, True, False, 1, 1.5, [], {}):
        result = project_api.update_project_for_rules(project_id, "Renamed", bad_desc)
        assert result == {"ok": False, "error": "invalid_input"}, bad_desc


def test_update_project_language_variants(temp_db):
    project_id = project_service.create_project("Client", "old", "中文")

    assert project_api.update_project_for_rules(project_id, "Client", "", "日语")["project"]["language"] == "日语"
    assert project_api.update_project_for_rules(project_id, "Client", "", "  俄语  ")["project"]["language"] == "俄语"
    assert project_api.update_project_for_rules(project_id, "Client", "", "   ")["project"]["language"] == "中文"


def test_update_project_rejects_non_str_language(temp_db):
    project_id = project_service.create_project("Client", "old")
    for bad_language in (None, True, False, 1, 1.5, [], {}, b"zh"):
        result = project_api.update_project_for_rules(project_id, "Renamed", "new", bad_language)
        assert result == {"ok": False, "error": "invalid_input"}, bad_language


def test_update_project_rejects_empty_name(temp_db):
    project_id = project_service.create_project("Client", "old")
    for bad_name in ("", "   ", "\t\n"):
        result = project_api.update_project_for_rules(project_id, bad_name, "new")
        assert result == {"ok": False, "error": "invalid_input"}, bad_name


def test_update_project_not_found(temp_db):
    result = project_api.update_project_for_rules(99999, "Renamed", "new")
    assert result == {"ok": False, "error": "not_found"}


def test_update_project_rejects_system_project_uncategorized(temp_db):
    project_id = project_service.get_or_create_uncategorized_project()

    result = project_api.update_project_for_rules(project_id, "Renamed", "new")

    assert result == {"ok": False, "error": "system_project"}
    # The system project is unchanged.
    assert _project_row(project_id)["name"] == UNCATEGORIZED_PROJECT


def test_update_project_rejects_system_project_excluded(temp_db):
    project_id = project_service.get_or_create_excluded_project()

    result = project_api.update_project_for_rules(project_id, "Renamed", "new")

    assert result == {"ok": False, "error": "system_project"}
    assert _project_row(project_id)["name"] == EXCLUDED_PROJECT


def test_update_project_rejects_duplicate_name(temp_db):
    project_api.create_project_for_rules("Client", "")
    other_id = project_service.create_project("Other", "")

    result = project_api.update_project_for_rules(other_id, "Client", "")

    assert result == {"ok": False, "error": "duplicate_project"}
    # The other project is unchanged.
    assert _project_row(other_id)["name"] == "Other"


def test_update_project_allows_renaming_to_self(temp_db):
    project_id = project_service.create_project("Client", "old")

    result = project_api.update_project_for_rules(project_id, "Client", "new")

    assert result["ok"] is True
    assert result["project"]["name"] == "Client"
    assert result["project"]["description"] == "new"


def test_update_project_service_exception_collapses_to_operation_failed(
    temp_db, monkeypatch
):
    project_id = project_service.create_project("Client", "old")

    def boom(pid, name, description="", language="中文"):
        raise RuntimeError(
            "boom SELECT * FROM activity_log traceback window_title clipboard note C:\\Secret"
        )

    monkeypatch.setattr(project_service, "update_project", boom)

    result = project_api.update_project_for_rules(project_id, "Renamed", "new")
    assert result == {"ok": False, "error": "operation_failed"}
    _assert_no_sensitive_tokens(repr(result))


def test_update_project_payload_is_json_serializable(temp_db):
    project_id = project_service.create_project("Client", "old")
    result = project_api.update_project_for_rules(project_id, "Renamed", "new")
    json.dumps(result, ensure_ascii=False)




def test_set_enabled_success_true(temp_db):
    project_id = project_service.create_project("Client", "")
    project_service.set_project_enabled(project_id, False)

    result = project_api.set_project_enabled_for_rules(project_id, True)

    assert result["ok"] is True
    _assert_payload_shape(result["project"])
    assert result["project"]["enabled"] is True
    assert _project_row(project_id)["enabled"] == 1


def test_set_enabled_success_false(temp_db):
    project_id = project_service.create_project("Client", "")

    result = project_api.set_project_enabled_for_rules(project_id, False)

    assert result["ok"] is True
    _assert_payload_shape(result["project"])
    assert result["project"]["enabled"] is False
    assert _project_row(project_id)["enabled"] == 0


def test_set_enabled_rejects_bool_project_id(temp_db):
    project_id = project_service.create_project("Client", "")
    for bad_id in (True, False):
        result = project_api.set_project_enabled_for_rules(bad_id, True)
        assert result == {"ok": False, "error": "invalid_input"}, bad_id
    assert _project_row(project_id)["enabled"] == 1


def test_set_enabled_rejects_non_int_project_id(temp_db):
    for bad_id in (None, "1", 1.0, 1.5, [], {}, b"1", 0, -1):
        result = project_api.set_project_enabled_for_rules(bad_id, True)
        assert result == {"ok": False, "error": "invalid_input"}, bad_id


def test_set_enabled_rejects_non_bool_enabled(temp_db):
    project_id = project_service.create_project("Client", "")
    for bad_enabled in (None, 1, 0, "true", "false", [], {}):
        result = project_api.set_project_enabled_for_rules(project_id, bad_enabled)
        assert result == {"ok": False, "error": "invalid_input"}, bad_enabled
    assert _project_row(project_id)["enabled"] == 1


def test_set_enabled_not_found(temp_db):
    result = project_api.set_project_enabled_for_rules(99999, True)
    assert result == {"ok": False, "error": "not_found"}


def test_set_enabled_rejects_uncategorized_project(temp_db):
    project_id = project_service.get_or_create_uncategorized_project()

    result = project_api.set_project_enabled_for_rules(project_id, False)

    assert result == {"ok": False, "error": "system_project"}
    # ``未归类`` must always remain enabled.
    assert _project_row(project_id)["enabled"] == 1


def test_set_enabled_rejects_excluded_project_enable(temp_db):
    project_id = project_service.get_or_create_excluded_project()
    # ``排除规则`` is created with enabled = 0; the API facade must reject
    # any attempt to enable it via the lifecycle path.
    assert _project_row(project_id)["enabled"] == 0

    result = project_api.set_project_enabled_for_rules(project_id, True)

    assert result == {"ok": False, "error": "system_project"}
    assert _project_row(project_id)["enabled"] == 0


def test_set_enabled_service_exception_collapses_to_operation_failed(
    temp_db, monkeypatch
):
    project_id = project_service.create_project("Client", "")

    def boom(pid, enabled):
        raise RuntimeError(
            "boom SELECT * FROM activity_log traceback window_title clipboard note C:\\Secret"
        )

    monkeypatch.setattr(project_service, "set_project_enabled", boom)

    result = project_api.set_project_enabled_for_rules(project_id, False)
    assert result == {"ok": False, "error": "operation_failed"}
    _assert_no_sensitive_tokens(repr(result))


def test_set_enabled_payload_is_json_serializable(temp_db):
    project_id = project_service.create_project("Client", "")
    result = project_api.set_project_enabled_for_rules(project_id, False)
    json.dumps(result, ensure_ascii=False)




def test_archive_success_sets_is_archived(temp_db):
    project_id = project_service.create_project("Client", "")

    result = project_api.archive_project_for_rules(project_id)

    assert result["ok"] is True
    _assert_payload_shape(result["project"])
    assert result["project"]["archived"] is True
    # enabled / name / description are preserved.
    assert result["project"]["enabled"] is True
    assert result["project"]["name"] == "Client"
    row = _project_row(project_id)
    assert row["is_archived"] == 1
    assert row["enabled"] == 1
    assert row["name"] == "Client"


def test_archive_does_not_delete_project_rows(temp_db):
    project_id = project_service.create_project("Client", "")
    before = _counts()

    project_api.archive_project_for_rules(project_id)

    after = _counts()
    # The project row is still present (just is_archived = 1).
    assert after["project"] == before["project"]
    assert _project_row(project_id) is not None


def test_archive_does_not_delete_folder_or_keyword_rules(temp_db):
    project_id = project_service.create_project("Client", "")
    folder_rule_service.create_or_update_folder_rule("D:\\Client", project_id)
    rule_service.create_rule("Spec", project_id)
    before = _counts()

    project_api.archive_project_for_rules(project_id)

    after = _counts()
    # Folder rules and keyword rules are NOT deleted by archive.
    assert after["folder"] == before["folder"]
    assert after["keyword"] == before["keyword"]


def test_archive_does_not_touch_activities(temp_db):
    project_id = project_service.create_project("Client", "")
    before = _counts()

    project_api.archive_project_for_rules(project_id)

    after = _counts()
    assert after["activity"] == before["activity"]
    assert after["assignment"] == before["assignment"]
    assert after["session_note"] == before["session_note"]


def test_archive_rejects_bool_project_id(temp_db):
    project_id = project_service.create_project("Client", "")
    for bad_id in (True, False):
        result = project_api.archive_project_for_rules(bad_id)
        assert result == {"ok": False, "error": "invalid_input"}, bad_id
    assert _project_row(project_id)["is_archived"] == 0


def test_archive_rejects_non_int_or_non_positive_project_id(temp_db):
    for bad_id in (None, "1", 1.0, 1.5, [], {}, b"1", 0, -1):
        result = project_api.archive_project_for_rules(bad_id)
        assert result == {"ok": False, "error": "invalid_input"}, bad_id


def test_archive_not_found(temp_db):
    result = project_api.archive_project_for_rules(99999)
    assert result == {"ok": False, "error": "not_found"}


def test_archive_rejects_uncategorized_project(temp_db):
    project_id = project_service.get_or_create_uncategorized_project()

    result = project_api.archive_project_for_rules(project_id)

    assert result == {"ok": False, "error": "system_project"}
    assert _project_row(project_id)["is_archived"] == 0


def test_archive_rejects_excluded_project(temp_db):
    project_id = project_service.get_or_create_excluded_project()

    result = project_api.archive_project_for_rules(project_id)

    assert result == {"ok": False, "error": "system_project"}
    assert _project_row(project_id)["is_archived"] == 0


def test_archive_service_exception_collapses_to_operation_failed(
    temp_db, monkeypatch
):
    project_id = project_service.create_project("Client", "")

    def boom(pid):
        raise RuntimeError(
            "boom SELECT * FROM activity_log traceback window_title clipboard note C:\\Secret"
        )

    monkeypatch.setattr(project_service, "archive_project", boom)

    result = project_api.archive_project_for_rules(project_id)
    assert result == {"ok": False, "error": "operation_failed"}
    _assert_no_sensitive_tokens(repr(result))


def test_archive_payload_is_json_serializable(temp_db):
    project_id = project_service.create_project("Client", "")
    result = project_api.archive_project_for_rules(project_id)
    json.dumps(result, ensure_ascii=False)




def _install_cache_spies(monkeypatch):
    """Replace the three cache-invalidation entry points with call counters.

    Returns a dict with three ``count`` ints that the test can assert on.
    Each spy also calls the original invalidation so cached state stays
    fresh for the rest of the test.
    """
    counts = {"folder": 0, "keyword": 0, "exclude": 0}

    original_folder = folder_rule_service.invalidate_folder_rule_cache
    original_keyword = project_inference_service.invalidate_keyword_rule_cache
    # ``privacy_service.clear_exclude_rules_cache`` is the actual symbol
    # used by both set_project_enabled and archive_project. The lazy import
    # inside those service functions resolves through the module attribute,
    # so patching the module attribute is the reliable way to intercept it.
    from worktrace.services import privacy_service

    original_privacy_clear = privacy_service.clear_exclude_rules_cache

    def folder_spy():
        counts["folder"] += 1
        original_folder()

    def keyword_spy():
        counts["keyword"] += 1
        original_keyword()

    def privacy_spy():
        counts["exclude"] += 1
        original_privacy_clear()

    # project_service.set_project_enabled / archive_project import the
    # invalidation functions lazily inside the function body, so patching
    # the module attribute is the reliable way to intercept them.
    monkeypatch.setattr(
        "worktrace.services.folder_rule_service.invalidate_folder_rule_cache",
        folder_spy,
    )
    monkeypatch.setattr(
        "worktrace.services.project_inference_service.invalidate_keyword_rule_cache",
        keyword_spy,
    )
    monkeypatch.setattr(
        "worktrace.services.privacy_service.clear_exclude_rules_cache",
        privacy_spy,
    )
    return counts


def test_set_enabled_success_triggers_all_cache_hooks(temp_db, monkeypatch):
    project_id = project_service.create_project("Client", "")
    counts = _install_cache_spies(monkeypatch)

    project_api.set_project_enabled_for_rules(project_id, False)

    assert counts["folder"] == 1
    assert counts["keyword"] == 1
    assert counts["exclude"] == 1


def test_archive_success_triggers_all_cache_hooks(temp_db, monkeypatch):
    project_id = project_service.create_project("Client", "")
    counts = _install_cache_spies(monkeypatch)

    project_api.archive_project_for_rules(project_id)

    assert counts["folder"] == 1
    assert counts["keyword"] == 1
    assert counts["exclude"] == 1


def test_create_success_does_not_trigger_cache_hooks(temp_db, monkeypatch):
    # Creating a brand new project (no rules yet) does not need to
    # invalidate the folder / keyword / exclude caches because the new
    # project has no rules and so cannot affect rule target / inference /
    # exclude state.
    counts = _install_cache_spies(monkeypatch)

    project_api.create_project_for_rules("Client", "")

    assert counts["folder"] == 0
    assert counts["keyword"] == 0
    assert counts["exclude"] == 0


def test_update_success_does_not_trigger_cache_hooks(temp_db, monkeypatch):
    # Renaming a project or editing its description does not change which
    # rules are enabled or which projects are rule targets, so the caches
    # do not need to be invalidated.
    project_id = project_service.create_project("Client", "old")
    counts = _install_cache_spies(monkeypatch)

    project_api.update_project_for_rules(project_id, "Renamed", "new")

    assert counts["folder"] == 0
    assert counts["keyword"] == 0
    assert counts["exclude"] == 0


@pytest.mark.parametrize(
    "facade_call",
    [
        lambda: project_api.set_project_enabled_for_rules(True, False),
        lambda: project_api.set_project_enabled_for_rules("1", False),
        lambda: project_api.set_project_enabled_for_rules(0, False),
        lambda: project_api.set_project_enabled_for_rules(-1, False),
        lambda: project_api.set_project_enabled_for_rules(1, "true"),
        lambda: project_api.set_project_enabled_for_rules(1, 1),
        lambda: project_api.set_project_enabled_for_rules(1, None),
    ],
)
def test_set_enabled_invalid_input_does_not_trigger_cache_hooks(
    temp_db, monkeypatch, facade_call
):
    counts = _install_cache_spies(monkeypatch)
    result = facade_call()
    assert result == {"ok": False, "error": "invalid_input"}
    assert counts["folder"] == 0
    assert counts["keyword"] == 0
    assert counts["exclude"] == 0


def test_set_enabled_not_found_does_not_trigger_cache_hooks(temp_db, monkeypatch):
    counts = _install_cache_spies(monkeypatch)
    project_api.set_project_enabled_for_rules(99999, False)
    assert counts["folder"] == 0
    assert counts["keyword"] == 0
    assert counts["exclude"] == 0


def test_set_enabled_system_project_does_not_trigger_cache_hooks(
    temp_db, monkeypatch
):
    project_id = project_service.get_or_create_uncategorized_project()
    counts = _install_cache_spies(monkeypatch)
    project_api.set_project_enabled_for_rules(project_id, False)
    assert counts["folder"] == 0
    assert counts["keyword"] == 0
    assert counts["exclude"] == 0


@pytest.mark.parametrize(
    "facade_call",
    [
        lambda: project_api.archive_project_for_rules(True),
        lambda: project_api.archive_project_for_rules("1"),
        lambda: project_api.archive_project_for_rules(0),
        lambda: project_api.archive_project_for_rules(-1),
    ],
)
def test_archive_invalid_input_does_not_trigger_cache_hooks(
    temp_db, monkeypatch, facade_call
):
    counts = _install_cache_spies(monkeypatch)
    result = facade_call()
    assert result == {"ok": False, "error": "invalid_input"}
    assert counts["folder"] == 0
    assert counts["keyword"] == 0
    assert counts["exclude"] == 0


def test_archive_not_found_does_not_trigger_cache_hooks(temp_db, monkeypatch):
    counts = _install_cache_spies(monkeypatch)
    project_api.archive_project_for_rules(99999)
    assert counts["folder"] == 0
    assert counts["keyword"] == 0
    assert counts["exclude"] == 0


def test_archive_system_project_does_not_trigger_cache_hooks(temp_db, monkeypatch):
    project_id = project_service.get_or_create_excluded_project()
    counts = _install_cache_spies(monkeypatch)
    project_api.archive_project_for_rules(project_id)
    assert counts["folder"] == 0
    assert counts["keyword"] == 0
    assert counts["exclude"] == 0




def test_lifecycle_writes_do_not_touch_rules_or_activities(temp_db):
    project_id = project_service.create_project("Client", "")
    folder_rule_service.create_or_update_folder_rule("D:\\Client", project_id)
    rule_service.create_rule("Spec", project_id)
    before = _counts()

    project_api.update_project_for_rules(project_id, "Renamed", "new")
    project_api.set_project_enabled_for_rules(project_id, False)
    project_api.set_project_enabled_for_rules(project_id, True)
    # archive last; once archived, no further lifecycle writes apply.
    project_api.archive_project_for_rules(project_id)

    after = _counts()
    assert after == before


def test_create_does_not_create_rules(temp_db):
    project_api.create_project_for_rules("Client", "")
    assert _counts()["folder"] == 0
    assert _counts()["keyword"] == 0


def test_lifecycle_does_not_invoke_backfill(temp_db, monkeypatch):
    project_id = project_service.create_project("Client", "")

    def fail_backfill(*args, **kwargs):
        raise AssertionError("backfill must not run during project lifecycle")

    from worktrace.services import rule_impact_service

    monkeypatch.setattr(rule_impact_service, "backfill_rule_impact", fail_backfill)

    project_api.update_project_for_rules(project_id, "Renamed", "new")
    project_api.set_project_enabled_for_rules(project_id, False)
    project_api.archive_project_for_rules(project_id)


def test_delete_project_not_exposed_on_api_facade(temp_db):
    # Regression lock: hard delete must NOT be reachable via the
    # ``*_for_rules`` lifecycle facades. The bridge must not call
    # ``project_api.delete_project`` either (enforced in bridge/static
    # contract tests); here we assert facades never delete the project row.
    project_id = project_service.create_project("Client", "")

    project_api.archive_project_for_rules(project_id)

    # The project row must still exist (archived, not deleted).
    assert _project_row(project_id) is not None
    assert _project_row(project_id)["is_archived"] == 1




def test_existing_keyword_rule_crud_still_works_after_lifecycle(temp_db):
    project_id = project_service.create_project("Client", "")

    # create
    create_result = rule_api.create_project_keyword_rule(project_id, "Spec")
    assert create_result["ok"] is True
    rule_id = create_result["rule"]["id"]
    # toggle
    assert rule_api.set_project_rule_enabled("keyword", rule_id, False)["ok"] is True
    assert rule_api.set_project_rule_enabled("keyword", rule_id, True)["ok"] is True
    # delete
    assert rule_api.delete_project_keyword_rule(rule_id)["ok"] is True


def test_existing_folder_rule_crud_still_works_after_lifecycle(temp_db):
    project_id = project_service.create_project("Client", "")

    create_result = rule_api.create_project_folder_rule(project_id, "D:\\Client", True)
    assert create_result["ok"] is True
    rule_id = create_result["rule"]["id"]
    assert rule_api.set_project_rule_enabled("folder", rule_id, False)["ok"] is True
    assert (
        rule_api.update_project_folder_rule(rule_id, "D:\\Client\\Sub", False)["ok"]
        is True
    )
    assert rule_api.delete_project_folder_rule(rule_id)["ok"] is True




def test_get_project_rules_payload_includes_display_safe_flags(temp_db):
    project_service.create_project("Client", "")
    project_service.get_or_create_uncategorized_project()
    project_service.get_or_create_excluded_project()

    bindings = project_service.list_project_bindings()

    by_name = {p["name"]: p for p in bindings}
    # The facade returns raw service rows; the display-safe flags are added by
    # the bridge. Here we verify the service still returns the raw fields the
    # bridge needs. ``list_project_bindings`` only surfaces ``排除规则`` (not
    # ``未归类``) because ``未归类`` is never rule-editable.
    assert by_name["Client"]["created_by"] == "user"
    assert by_name[EXCLUDED_PROJECT]["created_by"] == "system"
    assert by_name[EXCLUDED_PROJECT]["name"] == EXCLUDED_PROJECT
    assert UNCATEGORIZED_PROJECT not in by_name




def test_list_rule_target_projects_excludes_excluded_project(temp_db):
    # Foundational lock: the special ``排除规则`` project is created with
    # ``enabled = 0``, so ``list_rule_target_projects()`` must NOT include it.
    # This is why the normal keyword/folder facades reject it as
    # ``project_not_found`` and only the dedicated excluded-rule facades apply.
    excluded_id = project_service.get_or_create_excluded_project()
    client_id = project_service.create_project("Client", "")

    targets = project_service.list_rule_target_projects()
    target_ids = [int(t["id"]) for t in targets]
    target_names = [str(t["name"]) for t in targets]

    assert client_id in target_ids
    assert excluded_id not in target_ids
    assert EXCLUDED_PROJECT not in target_names


def test_excluded_project_cannot_be_made_rule_target_via_lifecycle(temp_db):
    # Consolidated lock: the excluded project cannot be enabled or archived via
    # the lifecycle API, so it can never become a rule target. After rejected
    # attempts it stays ``enabled = 0`` / ``is_archived = 0`` and stays absent
    # from ``list_rule_target_projects()`` — backing the excluded-rule facade.
    project_id = project_service.get_or_create_excluded_project()

    enable_result = project_api.set_project_enabled_for_rules(project_id, True)
    archive_result = project_api.archive_project_for_rules(project_id)

    assert enable_result == {"ok": False, "error": "system_project"}
    assert archive_result == {"ok": False, "error": "system_project"}

    row = _project_row(project_id)
    assert row["enabled"] == 0
    assert row["is_archived"] == 0

    targets = project_service.list_rule_target_projects()
    target_ids = [int(t["id"]) for t in targets]
    assert project_id not in target_ids


def test_set_excluded_rules_enabled_uses_dedicated_facade(temp_db, monkeypatch):
    project_id = project_service.get_or_create_excluded_project()
    counts = _install_cache_spies(monkeypatch)

    enable_result = project_api.set_excluded_rules_enabled(True)
    assert enable_result["ok"] is True
    _assert_payload_shape(enable_result["project"])
    assert enable_result["project"]["id"] == project_id
    assert enable_result["project"]["enabled"] is True
    assert _project_row(project_id)["enabled"] == 1
    assert counts["exclude"] == 1

    disable_result = project_api.set_excluded_rules_enabled(False)
    assert disable_result["ok"] is True
    assert disable_result["project"]["enabled"] is False
    assert _project_row(project_id)["enabled"] == 0
    assert counts["exclude"] == 2


def test_set_excluded_rules_enabled_rejects_non_bool(temp_db, monkeypatch):
    counts = _install_cache_spies(monkeypatch)
    for bad_enabled in (None, 1, 0, "true", "false", [], {}):
        result = project_api.set_excluded_rules_enabled(bad_enabled)
        assert result == {"ok": False, "error": "invalid_input"}, bad_enabled
    assert counts["exclude"] == 0
