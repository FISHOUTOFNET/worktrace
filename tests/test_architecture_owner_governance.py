from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Iterable

import pytest

from worktrace.collector import collector as collector_module


pytestmark = [pytest.mark.unit, pytest.mark.contract]

ROOT = Path(__file__).resolve().parents[1]
PRODUCTION = ROOT / "worktrace"

_BANNED_FUNCTION_DEFINITIONS = {
    "apply_rules_to_activity",
    "apply_rules_to_unclassified",
    "backfill_missing_assignments",
    "get_activity_structure_marker_by_date",
    "get_activity_structure_markers",
    "get_or_create_excluded_project",
    "get_or_create_uncategorized_project",
    "invalidate_uncategorized_project_cache",
    "record_hard_boundary",
    "record_runtime_boundary",
    "update_project_editable_activities_project",
    "update_project_editable_activity_note",
}

_GENERATION_DML_OWNERS = {
    "settings": {
        "worktrace/db.py",
        "worktrace/schema_migrations.py",
        "worktrace/services/database_maintenance_service.py",
        "worktrace/services/installation_metadata_store.py",
        "worktrace/services/secure_backup_service.py",
        "worktrace/services/settings_service.py",
    },
    "project": {
        "worktrace/db.py",
        "worktrace/schema_migrations.py",
        "worktrace/services/database_maintenance_service.py",
        "worktrace/services/project_service.py",
        "worktrace/services/system_project_service.py",
    },
    "project_rule": {
        "worktrace/services/database_maintenance_service.py",
        "worktrace/services/rule_catalog_command_service.py",
    },
    "folder_project_rule": {
        "worktrace/services/database_maintenance_service.py",
        "worktrace/services/rule_catalog_command_service.py",
    },
    "activity_log": {
        "worktrace/schema_migrations.py",
        "worktrace/services/activity_fact_repository.py",
        "worktrace/services/activity_lifecycle_service.py",
        "worktrace/services/activity_resource_command_service.py",
        "worktrace/services/database_maintenance_service.py",
        "worktrace/services/privacy_anonymization_service.py",
        "worktrace/services/secure_backup_validation.py",
    },
    "activity_project_assignment": {
        "worktrace/services/activity_fact_repository.py",
        "worktrace/services/assignment_command_service.py",
        "worktrace/services/database_maintenance_service.py",
    },
    "activity_resource": {
        "worktrace/services/database_maintenance_service.py",
        "worktrace/services/resource_service.py",
    },
    "activity_clipboard_event": {
        "worktrace/services/activity_resource_command_service.py",
        "worktrace/services/clipboard_service.py",
        "worktrace/services/database_maintenance_service.py",
        "worktrace/services/privacy_anonymization_service.py",
    },
    "session_boundary": {
        "worktrace/services/database_maintenance_service.py",
        "worktrace/services/session_boundary_service.py",
    },
    "report_session_operation": {
        "worktrace/services/database_maintenance_service.py",
        "worktrace/services/report_session_operation_service.py",
    },
    "report_session_operation_member": {
        "worktrace/services/database_maintenance_service.py",
        "worktrace/services/report_session_operation_service.py",
    },
    "report_mutation_request": {
        "worktrace/services/database_maintenance_service.py",
        "worktrace/services/report_session_operation_service.py",
    },
    "history_mutation_job": {
        "worktrace/services/history_mutation_job_service.py",
    },
}

# Secure import mutates only its isolated staging database before atomic
# replacement, so it is the single database-replacement exception for these
# business tables rather than a second live command owner.
for _replacement_table in set(_GENERATION_DML_OWNERS) - {"history_mutation_job"}:
    _GENERATION_DML_OWNERS[_replacement_table].add(
        "worktrace/services/secure_backup_service.py"
    )

_DML_PATTERN = re.compile(
    r"\b(INSERT(?:\s+OR\s+\w+)?\s+INTO|REPLACE\s+INTO|UPDATE|DELETE\s+FROM)"
    r"\s+([a-z_][a-z0-9_]*)",
    re.IGNORECASE,
)

_PROJECT_API_EXPORTS = {
    "archive_project_for_rules",
    "create_project_for_rules",
    "delete_project_for_rules",
    "get_project",
    "get_project_by_name",
    "list_active_projects",
    "list_project_bindings",
    "list_rule_target_projects",
    "list_selectable_projects",
    "list_user_projects",
    "set_excluded_rules_enabled",
    "set_project_enabled_for_rules",
    "update_project_for_rules",
}

_RULE_API_EXPORTS = {
    "ProjectRuleWriteError",
    "create_excluded_folder_rule_for_webview",
    "create_excluded_keyword_rule_for_webview",
    "create_project_folder_rule",
    "create_project_keyword_rule",
    "delete_project_folder_rule",
    "delete_project_keyword_rule",
    "preview_folder_rule_conflicts",
    "set_project_rule_enabled",
    "update_project_folder_rule",
    "update_project_keyword_rule",
}


def _python_files() -> list[Path]:
    return sorted(PRODUCTION.rglob("*.py"))


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def test_platforms_and_resources_do_not_import_services_or_database() -> None:
    violations: list[str] = []
    for package in ("platforms", "resources"):
        for path in sorted((PRODUCTION / package).glob("*.py")):
            for node in ast.walk(_tree(path)):
                if isinstance(node, ast.Import):
                    forbidden = [
                        alias.name
                        for alias in node.names
                        if alias.name == "worktrace.db"
                        or alias.name.startswith("worktrace.services")
                    ]
                elif isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                    absolute_forbidden = (
                        module == "worktrace.db"
                        or module.startswith("worktrace.services")
                    )
                    relative_forbidden = node.level == 2 and (
                        module == "services"
                        or module.startswith("services.")
                        or (not module and any(alias.name == "db" for alias in node.names))
                    )
                    forbidden = [module] if absolute_forbidden or relative_forbidden else []
                else:
                    continue
                if forbidden:
                    violations.append(
                        f"{path.relative_to(ROOT).as_posix()}:{node.lineno}"
                    )
    assert violations == []


def _call_name(call: ast.Call) -> str:
    target = call.func
    if isinstance(target, ast.Name):
        return target.id
    if isinstance(target, ast.Attribute):
        return target.attr
    return ""


def _service_dependency_graph() -> dict[str, set[str]]:
    services = PRODUCTION / "services"
    modules = {path.stem for path in services.glob("*.py")}
    graph = {module: set() for module in modules}
    for path in sorted(services.glob("*.py")):
        source = path.stem
        for node in ast.walk(_tree(path)):
            targets: Iterable[str] = ()
            if isinstance(node, ast.Import):
                targets = (
                    alias.name.removeprefix("worktrace.services.").split(".")[0]
                    for alias in node.names
                    if alias.name.startswith("worktrace.services.")
                )
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if node.level == 1 and module:
                    targets = (module.split(".")[0],)
                elif node.level == 1:
                    targets = (alias.name.split(".")[0] for alias in node.names)
                elif module == "worktrace.services":
                    targets = (alias.name.split(".")[0] for alias in node.names)
                elif module.startswith("worktrace.services."):
                    targets = (
                        module.removeprefix("worktrace.services.").split(".")[0],
                    )
            graph[source].update(
                target for target in targets if target in modules and target != source
            )
    return graph


def _strongly_connected_components(
    graph: dict[str, set[str]],
) -> list[set[str]]:
    index = 0
    indexes: dict[str, int] = {}
    lowlinks: dict[str, int] = {}
    stack: list[str] = []
    stacked: set[str] = set()
    result: list[set[str]] = []

    def visit(node: str) -> None:
        nonlocal index
        indexes[node] = index
        lowlinks[node] = index
        index += 1
        stack.append(node)
        stacked.add(node)
        for target in graph[node]:
            if target not in indexes:
                visit(target)
                lowlinks[node] = min(lowlinks[node], lowlinks[target])
            elif target in stacked:
                lowlinks[node] = min(lowlinks[node], indexes[target])
        if lowlinks[node] != indexes[node]:
            return
        component: set[str] = set()
        while stack:
            target = stack.pop()
            stacked.remove(target)
            component.add(target)
            if target == node:
                break
        result.append(component)

    for node in graph:
        if node not in indexes:
            visit(node)
    return result


def _literal_dml(path: Path) -> list[tuple[int, str, str]]:
    statements: list[tuple[int, str, str]] = []
    for node in ast.walk(_tree(path)):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        for match in _DML_PATTERN.finditer(node.value):
            operation = match.group(1).upper().replace("\n", " ")
            statements.append((node.lineno, operation, match.group(2).lower()))
    return statements


def _dynamic_dml(path: Path) -> list[tuple[int, str, set[str]]]:
    """Resolve the deliberately narrow dynamic-table write boundaries."""

    relative = path.relative_to(ROOT).as_posix()
    statements: list[tuple[int, str, set[str]]] = []
    for node in ast.walk(_tree(path)):
        if not isinstance(node, ast.JoinedStr):
            continue
        prefix = "".join(
            value.value
            for value in node.values
            if isinstance(value, ast.Constant) and isinstance(value.value, str)
        ).strip()
        if _DML_PATTERN.search(prefix):
            continue
        operation = re.match(r"^(UPDATE|DELETE\s+FROM)\b", prefix, re.IGNORECASE)
        if operation is None:
            continue
        tables: set[str] = set()
        if relative == "worktrace/services/rule_catalog_command_service.py":
            tables = {"project_rule", "folder_project_rule"}
        elif relative == "worktrace/services/database_maintenance_service.py":
            tables = set(_GENERATION_DML_OWNERS) - {"history_mutation_job"}
        elif relative == "worktrace/services/secure_backup_service.py":
            tables = set(_GENERATION_DML_OWNERS) - {"history_mutation_job"}
        statements.append((node.lineno, operation.group(1).upper(), tables))
    return statements


def _static_all(path: Path) -> set[str]:
    for node in _tree(path).body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(
            isinstance(target, ast.Name) and target.id == "__all__"
            for target in node.targets
        ):
            continue
        value = ast.literal_eval(node.value)
        return {str(item) for item in value}
    raise AssertionError(f"missing static __all__: {path.relative_to(ROOT).as_posix()}")


def test_composition_root_imports_only_canonical_windows_adapter() -> None:
    runtime = _tree(PRODUCTION / "runtime" / "app_runtime.py")
    imports = {
        (node.module or "", alias.name)
        for node in ast.walk(runtime)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    assert ("platforms.windows_adapter", "WindowsAdapter") in {
        (module.lstrip("."), name) for module, name in imports
    }
    assert not (PRODUCTION / "platforms" / "hardened_windows_adapter.py").exists()
    assert all(
        "hardened_windows_adapter" not in path.read_text(encoding="utf-8")
        for path in _python_files()
    )


def test_retired_aliases_wrappers_and_backfills_cannot_return() -> None:
    definitions: dict[str, list[str]] = {}
    for path in _python_files():
        relative = path.relative_to(ROOT).as_posix()
        for node in ast.walk(_tree(path)):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                definitions.setdefault(node.name, []).append(relative)
    assert not (_BANNED_FUNCTION_DEFINITIONS & definitions.keys())
    assert not (PRODUCTION / "services" / "folder_index_recovery_service.py").exists()


def test_production_cannot_silently_swallow_broad_exceptions() -> None:
    offenders: list[str] = []
    for path in _python_files():
        relative = path.relative_to(ROOT).as_posix()
        for node in ast.walk(_tree(path)):
            if not isinstance(node, ast.ExceptHandler):
                continue
            if not isinstance(node.type, ast.Name) or node.type.id != "Exception":
                continue
            if len(node.body) == 1 and isinstance(node.body[0], ast.Pass):
                offenders.append(f"{relative}:{node.lineno}")
    assert offenders == []


def test_connection_accepting_boundaries_use_the_supplied_connection() -> None:
    offenders: list[str] = []
    for path in sorted((PRODUCTION / "services").rglob("*.py")):
        relative = path.relative_to(ROOT).as_posix()
        for function in (
            node
            for node in ast.walk(_tree(path))
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        ):
            parameter_names = {
                argument.arg
                for argument in (*function.args.posonlyargs, *function.args.args)
                if argument.arg in {"conn", "connection", "business_conn"}
            }
            if not parameter_names:
                continue
            loaded_names = {
                node.id
                for node in ast.walk(function)
                if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
            }
            for parameter in parameter_names:
                if parameter not in loaded_names:
                    offenders.append(f"{relative}:{function.name}:{parameter}")
    assert offenders == []


def test_folder_index_query_has_no_write_or_filesystem_capability() -> None:
    query_path = PRODUCTION / "services" / "folder_index_query_service.py"
    tree = _tree(query_path)
    imported_roots = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imported_roots.update(
        (node.module or "").split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    )
    assert not ({"os", "pathlib", "time"} & imported_roots)
    forbidden_calls = {
        "mark_index_stale",
        "request_rebuild_for_rule",
        "request_refresh_for_enabled_rules",
    }
    assert not {
        _call_name(node)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
    } & forbidden_calls
    dml = re.compile(r"^\s*(INSERT|UPDATE|DELETE|REPLACE|CREATE|DROP|ALTER)\b", re.I)
    assert not {
        value.value
        for value in ast.walk(tree)
        if isinstance(value, ast.Constant)
        and isinstance(value.value, str)
        and dml.match(value.value)
    }


def test_normal_api_cannot_repair_system_catalog() -> None:
    offenders: list[str] = []
    for path in sorted((PRODUCTION / "api").rglob("*.py")):
        relative = path.relative_to(ROOT).as_posix()
        for node in ast.walk(_tree(path)):
            if isinstance(node, ast.Call) and _call_name(node) == "ensure_system_projects":
                offenders.append(relative)
            if isinstance(node, ast.ImportFrom) and any(
                alias.name == "ensure_system_projects" for alias in node.names
            ):
                offenders.append(relative)
    assert offenders == []


def test_business_services_cannot_import_global_sql_classifier() -> None:
    offenders: list[str] = []
    for path in sorted((PRODUCTION / "services").rglob("*.py")):
        for node in ast.walk(_tree(path)):
            if isinstance(node, ast.ImportFrom) and (
                node.module or ""
            ).endswith("report_generation_classifier"):
                offenders.append(path.relative_to(ROOT).as_posix())
            if isinstance(node, ast.Import) and any(
                alias.name.endswith("report_generation_classifier")
                for alias in node.names
            ):
                offenders.append(path.relative_to(ROOT).as_posix())
    assert offenders == []


def test_database_replacement_does_not_enumerate_cache_fanout() -> None:
    replacement_paths = (
        PRODUCTION / "services" / "secure_backup_service.py",
        PRODUCTION / "services" / "database_maintenance_service.py",
    )
    offenders: list[str] = []
    for path in replacement_paths:
        for node in ast.walk(_tree(path)):
            if not isinstance(node, ast.Call):
                continue
            name = _call_name(node)
            if re.match(r"^(clear|invalidate)_.*cache$", name):
                offenders.append(f"{path.name}:{name}")
    assert offenders == []


def test_project_rules_layering_and_capabilities_remain_acyclic() -> None:
    api_root = PRODUCTION / "api"
    bridge_classes: list[str] = []
    webview_imports: list[str] = []
    ui_error_maps: list[str] = []
    for path in sorted(api_root.glob("*.py")):
        for node in ast.walk(_tree(path)):
            if isinstance(node, ast.ClassDef) and "Bridge" in node.name:
                bridge_classes.append(f"{path.name}:{node.name}")
            if isinstance(node, ast.ImportFrom) and "webview" in (node.module or ""):
                webview_imports.append(f"{path.name}:{node.lineno}")
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                if any(
                    isinstance(target, ast.Name) and target.id.endswith("_MESSAGES")
                    for target in targets
                ):
                    ui_error_maps.append(f"{path.name}:{node.lineno}")
    assert bridge_classes == []
    assert webview_imports == []
    assert ui_error_maps == []
    for path in sorted((PRODUCTION / "services").rglob("*.py")):
        modules = {
            node.module or ""
            for node in ast.walk(_tree(path))
            if isinstance(node, ast.ImportFrom)
        }
        assert not any(module.endswith("api") or ".api" in module for module in modules)


def test_project_rules_webview_ownership_is_explicit() -> None:
    old_owner = PRODUCTION / "api" / "project_rules_webview.py"
    bridge_path = PRODUCTION / "webview_ui" / "bridge_rules.py"
    presenter_path = PRODUCTION / "webview_ui" / "project_rules_presenter.py"
    assert not old_owner.exists()
    assert bridge_path.exists()
    assert presenter_path.exists()

    wildcard_imports: list[str] = []
    for path in sorted((PRODUCTION / "webview_ui").glob("bridge*.py")):
        for node in ast.walk(_tree(path)):
            if isinstance(node, ast.ImportFrom) and any(
                alias.name == "*" for alias in node.names
            ):
                wildcard_imports.append(f"{path.name}:{node.lineno}")
    assert wildcard_imports == []

    bridge_imports = {
        (node.level, node.module or "")
        for node in ast.walk(_tree(bridge_path))
        if isinstance(node, ast.ImportFrom)
    }
    assert bridge_imports == {
        (0, "__future__"),
        (0, "typing"),
        (2, "api"),
        (1, "project_rules_presenter"),
    }

    presenter_imports = {
        (node.level, node.module or "")
        for node in ast.walk(_tree(presenter_path))
        if isinstance(node, ast.ImportFrom)
    }
    assert presenter_imports == {(0, "__future__"), (0, "typing")}
    forbidden_io_names = {"open", "get_" + "connection", "execute", "commit"}
    forbidden_calls = {
        _call_name(node)
        for node in ast.walk(_tree(presenter_path))
        if isinstance(node, ast.Call)
        and _call_name(node) in forbidden_io_names
    }
    assert forbidden_calls == set()


def test_retired_compatibility_methods_do_not_reappear() -> None:
    recorder_tree = _tree(
        PRODUCTION / "collector" / "activity_session_recorder.py"
    )
    recorder = next(
        node
        for node in recorder_tree.body
        if isinstance(node, ast.ClassDef)
        and node.name == "ActivitySessionRecorder"
    )
    recorder_methods = {
        node.name
        for node in recorder.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert "split_at_midnight" not in recorder_methods

    gate_tree = _tree(PRODUCTION / "write_gate.py")
    gate = next(
        node
        for node in gate_tree.body
        if isinstance(node, ast.ClassDef)
        and node.name == "ProcessDatabaseWriteGate"
    )
    gate_methods = {
        node.name
        for node in gate.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert "acquire" not in gate_methods
    assert {"draining", "promote_to_exclusive"} <= gate_methods

    snapshot_definitions = {
        node.name
        for node in _tree(
            PRODUCTION / "services" / "report_projection_snapshot_service.py"
        ).body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert "snapshot_read_scope" not in snapshot_definitions


def test_folder_index_and_privacy_evidence_contracts_are_canonical() -> None:
    query_tree = _tree(
        PRODUCTION / "services" / "folder_index_query_service.py"
    )
    lookup = next(
        node
        for node in query_tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "lookup_indexed_paths_for_file_name"
    )
    calls = {
        _call_name(node)
        for node in ast.walk(lookup)
        if isinstance(node, ast.Call)
    }
    assert "target_matches_rule" in calls

    privacy_source = (
        PRODUCTION / "services" / "privacy_service.py"
    ).read_text(encoding="utf-8")
    assert "lookup_indexed_paths_for_file_name" in privacy_source
    assert "resolve_unique_path_from_title" not in privacy_source
    assert "PrivacyResolutionPending(\"privacy_path_unresolved\")" in privacy_source


def test_clipboard_maintenance_failure_is_best_effort(monkeypatch) -> None:
    failures: list[str] = []

    def fail_prune() -> None:
        raise RuntimeError("retention unavailable")

    monkeypatch.setattr(collector_module.clipboard_service, "prune_old_events", fail_prune)
    monkeypatch.setattr(
        collector_module.collector_health,
        "record_transient_failure",
        lambda phase, _exc, _at: failures.append(phase),
    )

    assert collector_module._run_clipboard_maintenance_tick() is None
    assert failures == ["clipboard_maintenance"]


def test_service_dependency_graph_is_acyclic_including_local_imports() -> None:
    graph = _service_dependency_graph()
    cycles = [
        sorted(component)
        for component in _strongly_connected_components(graph)
        if len(component) > 1
    ]
    assert cycles == [], f"service dependency cycles: {cycles}"


def test_generation_backed_dml_stays_with_canonical_command_owners() -> None:
    offenders: list[str] = []
    covered: set[str] = set()
    for path in _python_files():
        relative = path.relative_to(ROOT).as_posix()
        for line, operation, table in _literal_dml(path):
            owners = _GENERATION_DML_OWNERS.get(table)
            if owners is None:
                continue
            covered.add(table)
            if relative not in owners:
                offenders.append(f"{relative}:{line}: {operation} {table}")
        for line, operation, tables in _dynamic_dml(path):
            if not tables:
                offenders.append(f"{relative}:{line}: {operation} <dynamic-table>")
                continue
            for table in tables:
                covered.add(table)
                if relative not in _GENERATION_DML_OWNERS[table]:
                    offenders.append(f"{relative}:{line}: {operation} {table}")
    assert covered == set(_GENERATION_DML_OWNERS), (
        "generation-backed tables missing from DML scan: "
        f"{sorted(set(_GENERATION_DML_OWNERS) - covered)}"
    )
    assert offenders == [], "non-canonical DML owners:\n" + "\n".join(offenders)


def test_public_project_and_rule_exports_are_validated_capabilities() -> None:
    assert _static_all(PRODUCTION / "api" / "project_api.py") == _PROJECT_API_EXPORTS
    assert _static_all(PRODUCTION / "api" / "rule_api.py") == _RULE_API_EXPORTS


def test_folder_matching_has_one_pure_canonical_policy() -> None:
    policy_path = PRODUCTION / "services" / "folder_rule_matching_policy.py"
    policy_tree = _tree(policy_path)
    imported_modules = {
        node.module or ""
        for node in ast.walk(policy_tree)
        if isinstance(node, ast.ImportFrom)
    }
    assert not any(
        module.endswith("db") or module.endswith("services")
        for module in imported_modules
    )
    for name in (
        "folder_rule_service.py",
        "folder_index_query_service.py",
        "rule_planning_service.py",
    ):
        source = (PRODUCTION / "services" / name).read_text(encoding="utf-8")
        assert "folder_rule_matching_policy" in source, name
    query = (PRODUCTION / "services" / "folder_index_query_service.py").read_text(
        encoding="utf-8"
    )
    service = (PRODUCTION / "services" / "folder_rule_service.py").read_text(
        encoding="utf-8"
    )
    assert "folder_rule_service" not in query
    assert "folder_index_query_service" not in service


def test_clipboard_fact_queries_are_separate_from_command_owner() -> None:
    command_path = PRODUCTION / "services" / "clipboard_service.py"
    query_path = PRODUCTION / "services" / "clipboard_fact_query_service.py"
    command_functions = {
        node.name
        for node in _tree(command_path).body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert not command_functions & {
        "clipboard_text_for_activity",
        "clipboard_times_for_activity_ids",
        "find_activity_for_clipboard_event",
        "list_file_text_mappings",
    }
    inference = (
        PRODUCTION / "services" / "project_inference_service.py"
    ).read_text(encoding="utf-8")
    assert "clipboard_fact_query_service" in inference
    assert "clipboard_service" not in inference
    assert _literal_dml(query_path) == []
