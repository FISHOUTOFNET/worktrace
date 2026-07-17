from pathlib import Path

import pytest

from tests.support import activity_factory as activity_service
from worktrace.api import rule_api
from worktrace.db import get_connection
from worktrace.platforms import windows_adapter
from worktrace.platforms.base import ActiveWindow
from worktrace.services import (
    folder_index_query_service,
    folder_index_service,
    folder_rule_service,
    privacy_service,
    project_service,
)
from worktrace.services.project_inference_service import assign_project_for_activity

pytestmark = [pytest.mark.db, pytest.mark.integration]


def _ready_index(rule_id: int, valid_from: str = "2026-06-18 00:00:00") -> None:
    assert folder_index_service.rebuild_folder_index(rule_id)
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE folder_rule_index_state
            SET status = 'ready', valid_from = ?
            WHERE folder_rule_id = ?
            """,
            (valid_from, rule_id),
        )


def test_folder_index_scans_all_extensions_and_casefolds_names(
    temp_db,
    tmp_path,
):
    project = project_service.create_project("Client")
    folder = tmp_path / "Client"
    sub = folder / "Sub"
    sub.mkdir(parents=True)
    chinese = folder / "合同.DOCX"
    code = sub / "MAIN.py"
    chinese.write_text("doc", encoding="utf-8")
    code.write_text("print(1)", encoding="utf-8")
    rule_id = folder_rule_service.create_or_update_folder_rule(str(folder), project)
    _ready_index(rule_id)

    chinese_matches = folder_index_query_service.lookup_indexed_paths_for_file_name(
        "合同.docx",
        "2026-06-18 09:00:00",
    )
    code_matches = folder_index_query_service.lookup_indexed_paths_for_file_name(
        "main.py",
        "2026-06-18 09:00:00",
    )

    assert [Path(row["file_path"]).name for row in chinese_matches] == ["合同.DOCX"]
    assert [Path(row["file_path"]).name for row in code_matches] == ["MAIN.py"]


def test_disabled_folder_rule_index_is_retained_but_not_used(temp_db, tmp_path):
    project = project_service.create_project("Client")
    folder = tmp_path / "Client"
    folder.mkdir()
    (folder / "Spec.docx").write_text("doc", encoding="utf-8")
    rule_id = folder_rule_service.create_or_update_folder_rule(str(folder), project)
    _ready_index(rule_id)

    folder_rule_service.set_folder_rule_enabled(rule_id, False)

    assert (
        folder_index_query_service.lookup_indexed_paths_for_file_name(
            "Spec.docx",
            "2026-06-18 09:00:00",
        )
        == []
    )
    with get_connection() as conn:
        assert (
            conn.execute(
                "SELECT COUNT(*) AS c FROM folder_rule_file_index WHERE folder_rule_id = ?",
                (rule_id,),
            ).fetchone()["c"]
            == 1
        )


def test_missing_indexed_path_requires_explicit_stale_command(temp_db, tmp_path):
    project = project_service.create_project("Client")
    folder = tmp_path / "Client"
    folder.mkdir()
    path = folder / "Spec.docx"
    path.write_text("doc", encoding="utf-8")
    rule_id = folder_rule_service.create_or_update_folder_rule(str(folder), project)
    _ready_index(rule_id)

    path.unlink()

    # Pure queries return the currently published durable snapshot. They do not
    # consult the live filesystem or mutate index state on read.
    matches = folder_index_query_service.lookup_indexed_paths_for_file_name(
        "Spec.docx",
        "2026-06-18 09:00:00",
    )
    assert len(matches) == 1
    assert Path(matches[0]["file_path"]).name == "Spec.docx"
    with get_connection() as conn:
        state = conn.execute(
            "SELECT status, refresh_requested FROM folder_rule_index_state WHERE folder_rule_id = ?",
            (rule_id,),
        ).fetchone()
    assert state["status"] == "ready"

    folder_index_service.mark_index_stale(rule_id, "indexed path missing")
    with get_connection() as conn:
        state = conn.execute(
            "SELECT status, refresh_requested FROM folder_rule_index_state WHERE folder_rule_id = ?",
            (rule_id,),
        ).fetchone()
    assert state["status"] == "stale"
    assert state["refresh_requested"] == 1


def test_title_only_activity_matches_indexed_folder_rule_for_any_extension(
    temp_db,
    tmp_path,
):
    project = project_service.create_project("Development")
    folder = tmp_path / "Repo"
    folder.mkdir()
    (folder / "main.py").write_text("print(1)", encoding="utf-8")
    rule_id = folder_rule_service.create_or_update_folder_rule(str(folder), project)
    _ready_index(rule_id)
    activity_id = activity_service.create_activity(
        "Visual Studio Code",
        "Code.exe",
        "main.py - Visual Studio Code",
        start_time="2026-06-18 09:00:00",
    )

    assignment = assign_project_for_activity(activity_id)

    assert assignment["source"] == "folder_rule"
    assert activity_service.get_activity(activity_id)["project_id"] == project


def test_cross_project_same_file_name_is_ambiguous(temp_db, tmp_path):
    project_a = project_service.create_project("A")
    project_b = project_service.create_project("B")
    folder_a = tmp_path / "A"
    folder_b = tmp_path / "B"
    folder_a.mkdir()
    folder_b.mkdir()
    (folder_a / "report.docx").write_text("a", encoding="utf-8")
    (folder_b / "report.docx").write_text("b", encoding="utf-8")
    rule_a = folder_rule_service.create_or_update_folder_rule(str(folder_a), project_a)
    rule_b = folder_rule_service.create_or_update_folder_rule(str(folder_b), project_b)
    _ready_index(rule_a)
    _ready_index(rule_b)
    activity_id = activity_service.create_activity(
        "Word",
        "winword.exe",
        "report.docx - Word",
        start_time="2026-06-18 09:00:00",
    )

    assignment = assign_project_for_activity(activity_id)

    assert assignment["source"] == "uncategorized"
    assert activity_service.get_activity(activity_id)["project_id"] != project_a
    assert activity_service.get_activity(activity_id)["project_id"] != project_b


def test_safe_backfill_uses_index_only_after_valid_from(temp_db, tmp_path):
    project = project_service.create_project("Client")
    folder = tmp_path / "Client"
    folder.mkdir()
    (folder / "report.docx").write_text("doc", encoding="utf-8")
    rule_id = folder_rule_service.create_or_update_folder_rule(str(folder), project)
    _ready_index(rule_id, valid_from="2026-06-18 10:00:00")
    early = activity_service.create_activity(
        "Word",
        "winword.exe",
        "report.docx - Word",
        start_time="2026-06-18 09:00:00",
    )
    activity_service.close_activity_row(early, "2026-06-18 09:10:00")
    late = activity_service.create_activity(
        "Word",
        "winword.exe",
        "report.docx - Word",
        start_time="2026-06-18 11:00:00",
    )
    activity_service.close_activity_row(late, "2026-06-18 11:10:00")

    result = rule_api.backfill_project_rule("folder", rule_id)

    assert result["ok"] is True
    assert result["result"]["updated_count"] == 1
    assert activity_service.get_activity(early)["project_id"] != project
    assert activity_service.get_activity(late)["project_id"] == project


def test_windows_adapter_uses_folder_index_after_open_files_miss(
    temp_db,
    tmp_path,
    monkeypatch,
):
    project = project_service.create_project("Development")
    folder = tmp_path / "Repo"
    folder.mkdir()
    path = folder / "main.py"
    path.write_text("print(1)", encoding="utf-8")
    rule_id = folder_rule_service.create_or_update_folder_rule(str(folder), project)
    _ready_index(rule_id)
    monkeypatch.setattr(windows_adapter, "_com_candidates", lambda _process_name: [])
    monkeypatch.setattr(
        windows_adapter,
        "_get_process_open_file_paths",
        lambda _pid: [],
    )

    resolved = windows_adapter._resolve_active_file_path(
        "Code.exe",
        "main.py - Visual Studio Code",
        900001,
    )

    assert Path(resolved) == path


def test_indexed_exclude_folder_anonymizes_title_only_activity(temp_db, tmp_path):
    excluded_project = project_service.get_or_create_excluded_project()
    project_service.set_project_enabled(excluded_project, True)
    folder = tmp_path / "Private"
    folder.mkdir()
    (folder / "secret.txt").write_text("secret", encoding="utf-8")
    rule_id = folder_rule_service.create_or_update_folder_rule(
        str(folder),
        excluded_project,
    )
    _ready_index(rule_id)

    assert privacy_service.is_excluded(
        ActiveWindow("Editor", "editor.exe", "secret.txt - Editor")
    )
