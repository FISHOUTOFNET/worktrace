from pathlib import Path

import pytest

from tests.support import activity_factory as activity_service
from worktrace.api import rule_history_api as rule_api
from worktrace.api import rule_api as catalog_rule_api
from worktrace.db import get_connection
from worktrace.platforms.base import ActiveWindow
from worktrace.platforms.windows_path_resolver import WindowsPathResolver
from worktrace.services import (
    folder_index_query_service,
    folder_index_service,
    folder_index_state_repository,
    folder_rule_service,
    privacy_service,
    project_service,
    rule_catalog_command_service,
)
from worktrace.services.project_inference_service import assign_project_for_activity

pytestmark = [pytest.mark.db, pytest.mark.integration]


def test_catalog_commit_persists_rebuild_marker_before_worker_wake(temp_db):
    project_id = project_service.create_project("Atomic Index Marker")

    rule_id = folder_rule_service.create_or_update_folder_rule(
        "D:\\AtomicIndex",
        project_id,
        True,
    )

    with get_connection() as conn:
        state = conn.execute(
            """
            SELECT status, build_status, refresh_requested
            FROM folder_rule_index_state
            WHERE folder_rule_id = ?
            """,
            (rule_id,),
        ).fetchone()
    assert dict(state) == {
        "status": "pending",
        "build_status": "pending",
        "refresh_requested": 1,
    }
    assert rule_id in folder_index_service._pending_rule_ids()


def test_worker_wake_failure_cannot_lose_durable_rebuild_request(
    temp_db,
    monkeypatch,
):
    project_id = project_service.create_project("Wake Failure")

    def fail_wake():
        raise RuntimeError("worker unavailable")

    monkeypatch.setattr(
        folder_index_service,
        "wake_folder_index_worker",
        fail_wake,
    )
    rule_id = folder_rule_service.create_or_update_folder_rule(
        "D:\\WakeFailure",
        project_id,
        True,
    )

    assert rule_id in folder_index_service._pending_rule_ids()
    folder_index_service.ensure_index_states_for_folder_rules()
    assert rule_id in folder_index_service._pending_rule_ids()


def test_index_state_failure_rolls_back_folder_rule_catalog_write(
    temp_db,
    monkeypatch,
):
    project_id = project_service.create_project("Index Rollback")

    def fail_state(_conn, _rule_id):
        raise RuntimeError("index state unavailable")

    monkeypatch.setattr(
        folder_index_state_repository,
        "request_rebuild",
        fail_state,
    )
    with pytest.raises(RuntimeError, match="index state unavailable"):
        folder_rule_service.create_or_update_folder_rule(
            "D:\\MustRollback",
            project_id,
            True,
        )

    with get_connection() as conn:
        assert conn.execute(
            "SELECT id FROM folder_project_rule WHERE folder_path = ?",
            ("D:\\MustRollback",),
        ).fetchone() is None


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


def test_folder_index_query_never_writes_or_checks_the_filesystem(temp_db, tmp_path):
    project = project_service.create_project("Read Only Index")
    folder = tmp_path / "ReadOnly"
    folder.mkdir()
    path = folder / "Gone.docx"
    path.write_text("doc", encoding="utf-8")
    rule_id = folder_rule_service.create_or_update_folder_rule(str(folder), project)
    _ready_index(rule_id)
    path.unlink()

    with get_connection() as conn:
        statements: list[str] = []
        before_changes = conn.total_changes
        conn.set_trace_callback(statements.append)
        matches = folder_index_query_service.lookup_indexed_paths_for_file_name(
            "Gone.docx",
            "2026-06-18 09:00:00",
            conn=conn,
        )
        conn.set_trace_callback(None)
        assert conn.total_changes == before_changes

    assert len(matches) == 1
    assert statements
    assert all(statement.lstrip().upper().startswith("SELECT") for statement in statements)


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


def test_windows_resolver_returns_none_after_live_sources_miss(
    temp_db,
    tmp_path,
):
    project = project_service.create_project("Development")
    folder = tmp_path / "Repo"
    folder.mkdir()
    path = folder / "main.py"
    path.write_text("print(1)", encoding="utf-8")
    rule_id = folder_rule_service.create_or_update_folder_rule(str(folder), project)
    _ready_index(rule_id)
    resolver = WindowsPathResolver()

    resolved = resolver.resolve(
        (10, 900001, "Code.exe", "main.py - Visual Studio Code"),
        "Code.exe",
        "main.py - Visual Studio Code",
        900001,
    )

    assert resolved is None


def test_indexed_exclude_folder_anonymizes_title_only_activity(temp_db, tmp_path):
    project_service.set_excluded_project_enabled(True)
    folder = tmp_path / "Private"
    folder.mkdir()
    (folder / "secret.txt").write_text("secret", encoding="utf-8")
    rule_id, _excluded_project = (
        rule_catalog_command_service.create_or_update_excluded_folder_rule(
            str(folder),
            recursive=True,
        )
    )
    _ready_index(rule_id)

    assert privacy_service.evaluate_exclusion(
        ActiveWindow("Editor", "editor.exe", "secret.txt - Editor")
    ).excluded is True


def test_edited_rule_filters_previous_active_generation_without_worker(
    temp_db,
    tmp_path,
):
    project = project_service.create_project("Moved Folder")
    old_folder = tmp_path / "Old"
    new_folder = tmp_path / "New"
    old_folder.mkdir()
    new_folder.mkdir()
    (old_folder / "brief.docx").write_text("old", encoding="utf-8")
    rule_id = folder_rule_service.create_or_update_folder_rule(
        str(old_folder),
        project,
    )
    _ready_index(rule_id)

    result = catalog_rule_api.update_project_folder_rule(
        rule_id,
        str(new_folder),
        True,
    )

    assert result["ok"] is True
    assert folder_index_query_service.lookup_indexed_paths_for_file_name(
        "brief.docx",
        "2026-06-18 09:00:00",
    ) == []
    with get_connection() as conn:
        state = conn.execute(
            """
            SELECT active_generation, refresh_requested
            FROM folder_rule_index_state
            WHERE folder_rule_id = ?
            """,
            (rule_id,),
        ).fetchone()
    assert state["active_generation"] is not None
    assert state["refresh_requested"] == 1


def test_edited_rule_preview_and_backfill_ignore_previous_generation(
    temp_db,
    tmp_path,
):
    project = project_service.create_project("Moved History Folder")
    old_folder = tmp_path / "HistoryOld"
    new_folder = tmp_path / "HistoryNew"
    old_folder.mkdir()
    new_folder.mkdir()
    (old_folder / "history.docx").write_text("old", encoding="utf-8")
    rule_id = folder_rule_service.create_or_update_folder_rule(
        str(old_folder),
        project,
    )
    _ready_index(rule_id)
    activity_id = activity_service.create_activity(
        "Word",
        "winword.exe",
        "history.docx - Word",
        start_time="2026-06-18 09:00:00",
    )
    activity_service.close_activity_row(activity_id, "2026-06-18 09:10:00")
    assert catalog_rule_api.update_project_folder_rule(
        rule_id,
        str(new_folder),
        True,
    )["ok"] is True

    preview = rule_api.preview_project_rule_impact("folder", rule_id)
    backfill = rule_api.backfill_project_rule("folder", rule_id)

    assert preview["ok"] is True
    assert preview["impact"]["counts"]["matched_count"] == 0
    assert preview["impact"]["counts"]["would_update_count"] == 0
    assert backfill["ok"] is True
    assert backfill["result"]["updated_count"] == 0
    assert activity_service.get_activity(activity_id)["project_id"] != project


def test_public_index_candidate_cannot_prove_unresolved_private_path_safe(
    temp_db,
    tmp_path,
):
    project_service.set_excluded_project_enabled(True)
    private_folder = tmp_path / "PrivateActual"
    public_folder = tmp_path / "PublicIndexed"
    private_folder.mkdir()
    public_folder.mkdir()
    rule_catalog_command_service.create_or_update_excluded_folder_rule(
        str(private_folder),
        recursive=True,
    )
    public_project = project_service.create_project("Public Candidate")
    (public_folder / "same.docx").write_text("public", encoding="utf-8")
    public_rule = folder_rule_service.create_or_update_folder_rule(
        str(public_folder),
        public_project,
    )
    _ready_index(public_rule)

    window = ActiveWindow(
        "Word",
        "winword.exe",
        "same.docx - Word",
        privacy_path_required=True,
    )
    decision = privacy_service.evaluate_exclusion(window)

    assert decision.excluded is True
    assert decision.resolution_pending is True
    assert decision.refresh_required is True
