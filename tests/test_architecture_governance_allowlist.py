from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.contract]

ROOT = Path(__file__).resolve().parents[1]
ALLOWLIST_PATH = ROOT / "architecture_governance_allowlist.json"


def _allowlist() -> dict[str, set[str]]:
    raw = json.loads(ALLOWLIST_PATH.read_text(encoding="utf-8"))
    return {name: set(paths) for name, paths in raw.items()}


def _production_files() -> list[Path]:
    return sorted((ROOT / "worktrace").rglob("*.py"))


def _relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _files_containing(token: str) -> set[str]:
    return {
        _relative(path)
        for path in _production_files()
        if token in path.read_text(encoding="utf-8")
    }


def test_governance_allowlist_paths_exist() -> None:
    for paths in _allowlist().values():
        for relative in paths:
            assert (ROOT / relative).is_file(), relative


def test_read_time_resource_detection_does_not_expand() -> None:
    offenders = {
        path
        for path in _files_containing("from ..resources.detectors import detect_resource")
        if "report" in path or "display" in path
    }
    assert offenders <= _allowlist()["read_time_resource_detection"]


def test_live_project_database_fallback_does_not_expand() -> None:
    offenders = {
        path
        for path in _files_containing("get_assignment_for_activity")
        if "live_display" in path or "activity_display_projection" in path
    }
    assert offenders <= _allowlist()["live_project_database_fallback"]


def test_sql_text_mutation_classification_does_not_expand() -> None:
    markers = {
        "_statement_affects_report_structure",
        "_setting_write_affects_report_structure",
        "REPORT_STRUCTURE_TABLES",
    }
    offenders = {
        _relative(path)
        for path in _production_files()
        if any(marker in path.read_text(encoding="utf-8") for marker in markers)
    }
    assert offenders <= _allowlist()["sql_text_mutation_classification"]


def test_runtime_payload_fallback_does_not_expand() -> None:
    js_files = sorted((ROOT / "worktrace" / "webview_ui" / "js").glob("*.js"))
    marker = "value.runtime && typeof value.runtime === \"object\" ? value.runtime : value"
    offenders = {
        _relative(path)
        for path in js_files
        if marker in path.read_text(encoding="utf-8")
    }
    assert offenders <= _allowlist()["runtime_payload_fallback"]


def test_runtime_global_registration_does_not_expand() -> None:
    markers = (
        "def set_runtime(",
        "def register_quiesce_handler(",
        "def register_collector_pause_handler(",
        "def register_collector_reset_handler(",
    )
    offenders = {
        _relative(path)
        for path in _production_files()
        if any(marker in path.read_text(encoding="utf-8") for marker in markers)
    }
    assert offenders <= _allowlist()["runtime_global_registration"]


def test_cross_module_private_imports_do_not_expand() -> None:
    offenders: set[str] = set()
    for path in _production_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            if not node.module or not node.module.endswith("live_display_service"):
                continue
            if any(alias.name.startswith("_") for alias in node.names):
                offenders.add(_relative(path))
    assert offenders <= _allowlist()["cross_module_private_import"]


def test_duplicate_live_contract_fields_do_not_expand() -> None:
    markers = ("active_elapsed_at_sample", "is_project_duration_live")
    offenders = {
        _relative(path)
        for path in _production_files()
        if any(marker in path.read_text(encoding="utf-8") for marker in markers)
    }
    assert offenders <= _allowlist()["duplicate_live_contract_fields"]
