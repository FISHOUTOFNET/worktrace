from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = [pytest.mark.contract, pytest.mark.db]

REPO_ROOT = Path(__file__).resolve().parents[1]

REPORT_PROJECTION_MODULES = [
    "worktrace/services/statistics_service.py",
    "worktrace/services/export_service.py",
    "worktrace/exports/excel_exporter.py",
    "worktrace/services/view_model_service.py",
]

OFFICIAL_ONLY_ACTIVITY_HELPERS = {
    "get_activities_by_range",
    "get_activities_by_date",
}


def test_report_projection_modules_do_not_use_activity_service_official_only_queries():
    violations: list[str] = []
    for relative_path in REPORT_PROJECTION_MODULES:
        path = REPO_ROOT / relative_path
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                imported = {alias.name for alias in node.names}
                if (
                    str(node.module or "").endswith("activity_service")
                    and imported & OFFICIAL_ONLY_ACTIVITY_HELPERS
                ):
                    names = ", ".join(sorted(imported & OFFICIAL_ONLY_ACTIVITY_HELPERS))
                    violations.append(f"{relative_path}: imports {names}")
            elif isinstance(node, ast.Call):
                func = node.func
                if (
                    isinstance(func, ast.Attribute)
                    and func.attr in OFFICIAL_ONLY_ACTIVITY_HELPERS
                    and isinstance(func.value, ast.Name)
                    and func.value.id == "activity_service"
                ):
                    violations.append(
                        f"{relative_path}:{node.lineno} calls activity_service.{func.attr}"
                    )
                elif (
                    isinstance(func, ast.Name)
                    and func.id in OFFICIAL_ONLY_ACTIVITY_HELPERS
                ):
                    violations.append(f"{relative_path}:{node.lineno} calls {func.id}")

    assert violations == []


def test_report_projection_modules_do_not_mutate_raw_activity_rows():
    mutation_helpers = {
        "increment_activity_duration",
        "set_activity_duration",
        "reopen_activity",
        "close_activity_row",
        "insert_activity_row",
        "delete_activity",
    }
    violations: list[str] = []
    for relative_path in REPORT_PROJECTION_MODULES + [
        "worktrace/services/report_session_projection_service.py",
        "worktrace/services/report_session_operation_engine.py",
        "worktrace/services/report_session_operation_service.py",
    ]:
        source = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
        tree = ast.parse(source, filename=relative_path)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr in mutation_helpers:
                    violations.append(f"{relative_path}:{node.lineno} calls {node.func.attr}")
    assert violations == []


def test_runtime_has_no_session_override_service_or_legacy_bridge_protocol():
    violations: list[str] = []
    for path in (REPO_ROOT / "worktrace").rglob("*"):
        if path.suffix not in {".py", ".js"}:
            continue
        rel = path.relative_to(REPO_ROOT).as_posix()
        source = path.read_text(encoding="utf-8")
        if rel == "worktrace/db.py":
            continue
        if "session_override_service" in source:
            violations.append(rel + " imports or references session_override_service")
        if rel.startswith("worktrace/webview_ui/js") and "save_timeline_session_override" in source:
            violations.append(rel + " exposes legacy activity-id edit bridge")
    assert violations == []


def test_report_projection_write_path_does_not_use_hidden_scope():
    source = (REPO_ROOT / "worktrace/services/timeline_service.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    violations = []
    write_nodes = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in {"update_session_override", "update_session_note_and_duration"}
    ]
    for node in ast.walk(ast.Module(body=write_nodes, type_ignores=[])):
        if isinstance(node, ast.keyword) and node.arg == "include_hidden":
            if isinstance(node.value, ast.Constant) and node.value.value is True:
                violations.append(node.lineno)
    assert violations == []


def test_cutover_removed_legacy_report_symbols_from_production():
    forbidden = {
        "ensure_context",
        "recompute_context_assignments_for_date",
        "persist_engine_match_states",
        "report_session_operation_dependency",
        "report_session_operation_supersession",
        "request_input_signature",
        "override_match_state",
        "refresh_revision",
        "live_state_revision",
        "display_projection_revision",
        "page_structure_revision",
    }
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (REPO_ROOT / "worktrace").rglob("*")
        if path.suffix in {".py", ".sql", ".js"}
    )
    assert {symbol for symbol in forbidden if symbol in source} == set()


def test_pure_engine_has_no_sqlite_or_webview_dependency():
    path = REPO_ROOT / "worktrace/services/report_session_operation_engine.py"
    source = path.read_text(encoding="utf-8")
    assert "sqlite" not in source.lower()
    assert "webview" not in source.lower()


def test_excel_and_csv_depend_on_canonical_snapshot_analytics():
    excel = (REPO_ROOT / "worktrace/exports/excel_exporter.py").read_text(encoding="utf-8")
    export = (REPO_ROOT / "worktrace/services/export_service.py").read_text(encoding="utf-8")
    assert "build_visible_snapshot" in excel and "build_statistics_projection" in excel
    assert "timeline_service" not in excel
    assert "build_visible_snapshot" in export and "build_statistics_projection" in export


def test_projection_engine_reuses_domain_freeze_thaw():
    source = (REPO_ROOT / "worktrace/services/report_session_operation_engine.py").read_text(encoding="utf-8")
    assert "def _freeze_value" not in source
    assert "def _mutable_value" not in source
    assert "_freeze_value = freeze_value" in source
    assert "_mutable_value = thaw_value" in source


def test_production_has_no_legacy_activity_id_mutation_resolvers():
    forbidden = {
        "resolve_current_session",
        "_coerce_activity_ids",
        "save_activity_session_override",
        "save_timeline_session_override",
    }
    source = chr(10).join(
        path.read_text(encoding="utf-8")
        for path in (REPO_ROOT / "worktrace").rglob("*")
        if path.suffix in {".py", ".js"}
    )
    assert {symbol for symbol in forbidden if symbol in source} == set()

