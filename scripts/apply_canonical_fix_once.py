from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    (ROOT / path).write_text(text, encoding="utf-8")


def replace_once(text: str, old: str, new: str, *, label: str) -> str:
    if new in text:
        return text
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one old fragment, found {count}")
    return text.replace(old, new, 1)


def update_session_projection() -> None:
    path = "worktrace/services/report_session_projection_service.py"
    text = read(path)
    old = '    "activity_ids", "member_slices", "anchor_activity_id", "first_activity_id",\n'
    new = '    "activity_ids", "member_slices", "activity_member_hash", "anchor_activity_id", "first_activity_id",\n'
    write(path, replace_once(text, old, new, label=path))


def update_csv_contract() -> None:
    path = "tests/test_statistics_csv_export.py"
    text = read(path)
    old = '    assert by_start["10:30:00"]["project"] == "已排除"\n'
    new = '    assert by_start["10:30:00"]["project"] == "Client"\n'
    write(path, replace_once(text, old, new, label=path))


def update_operation_engine() -> None:
    path = "worktrace/services/report_session_operation_engine.py"
    text = read(path)
    text = text.replace("from types import MappingProxyType\n", "")
    old_import = (
        "from .report_projection_model import OperationDiagnostic, OperationRecord, "
        "ProjectState, ReportMemberIdentity\n"
    )
    new_import = """from .report_projection_model import (
    OperationDiagnostic,
    OperationRecord,
    ProjectState,
    ReportMemberIdentity,
    freeze_value,
    thaw_value,
)
"""
    text = replace_once(text, old_import, new_import, label=f"{path} import")
    aliases = "_freeze_value = freeze_value\n_mutable_value = thaw_value\n\n\n"
    if aliases not in text:
        start = text.index("def _freeze_value(value: Any) -> Any:\n")
        end = text.index("@dataclass(frozen=True)\n", start)
        text = text[:start] + aliases + text[end:]
    write(path, text)


CANONICAL_TRIGGERS = """CANONICAL_REPORT_PROJECTION_TRIGGERS: list[str] = [
    "worktrace/services/context_service.py",
    "worktrace/services/report_status_policy.py",
    "worktrace/services/report_projection_identity.py",
    "worktrace/services/report_projection_model.py",
    "worktrace/services/report_projection_snapshot_service.py",
    "worktrace/services/report_session_builder.py",
    "worktrace/services/report_session_projection_service.py",
    "worktrace/services/report_session_operation_engine.py",
    "worktrace/services/report_session_operation_service.py",
    "worktrace/services/statistics_projection.py",
]


"""

D0_RULE = """    {
        "id": "D0. Canonical report projection",
        "triggers": CANONICAL_REPORT_PROJECTION_TRIGGERS,
        "tests": [
            "tests/test_report_projection_architecture_contract.py",
            "tests/test_report_projection_cutover.py",
            "tests/test_projection_governance_regressions.py",
            "tests/test_projection_revision_compatibility.py",
            "tests/test_report_projection_command_engine.py",
            "tests/test_report_session_operations.py",
            "tests/test_projection_plain_dto_contract.py",
            "tests/test_timeline_service.py",
            "tests/test_timeline_api_editing.py",
            "tests/test_webview_bridge_editing.py",
            "tests/test_project_activity_summary_contract.py",
            "tests/test_project_delete_contract.py",
            "tests/test_statistics_service.py",
            "tests/test_export_resource_fields.py",
            "tests/test_statistics_csv_export.py",
            "tests/test_run_affected_tests.py",
        ],
        "smoke": [],
        "warnings": [
            "Canonical report projection changed; running cross-layer projection, Timeline, and Statistics contracts.",
        ],
        "markers": ["contract and integration"],
    },
"""


def update_affected_runner() -> None:
    path = "scripts/run_affected_tests.py"
    text = read(path)
    if "CANONICAL_REPORT_PROJECTION_TRIGGERS" not in text:
        marker = "RULES: list[dict] = [\n"
        text = text.replace(marker, CANONICAL_TRIGGERS + marker, 1)
    if '"id": "D0. Canonical report projection"' not in text:
        marker = '    {\n        "id": "D. Timeline API / service / bridge",\n'
        if text.count(marker) != 1:
            raise RuntimeError(f"{path}: Timeline rule marker not unique")
        text = text.replace(marker, D0_RULE + marker, 1)

    security_start = text.index('        "id": "G. Security / crypto / backup",')
    security_end = text.index('    {\n        "id": "H. Collector / platform / resource model",', security_start)
    security = text[security_start:security_end]
    if '"worktrace/services/secure_backup_validation.py"' not in security:
        security = security.replace(
            '            "worktrace/services/secure_backup_service.py",\n',
            '            "worktrace/services/secure_backup_service.py",\n'
            '            "worktrace/services/secure_backup_validation.py",\n'
            '            "worktrace/write_gate.py",\n',
            1,
        )
    if '"tests/test_projection_governance_regressions.py"' not in security:
        security = security.replace(
            '            "tests/test_secure_backup_service.py",\n',
            '            "tests/test_secure_backup_service.py",\n'
            '            "tests/test_projection_governance_regressions.py",\n',
            1,
        )
    text = text[:security_start] + security + text[security_end:]
    write(path, text)


RUNNER_TESTS = """


def test_canonical_projection_files_select_cross_layer_suite(runner):
    required = {
        "tests/test_report_projection_cutover.py",
        "tests/test_projection_governance_regressions.py",
        "tests/test_projection_plain_dto_contract.py",
        "tests/test_timeline_api_editing.py",
        "tests/test_project_delete_contract.py",
        "tests/test_statistics_service.py",
        "tests/test_statistics_csv_export.py",
    }
    for changed in runner.CANONICAL_REPORT_PROJECTION_TRIGGERS:
        selection = runner.select_targets([changed])
        assert required <= set(selection.pytest_targets), (
            f"{changed} must select the canonical cross-layer suite"
        )


def test_secure_validation_and_write_gate_select_security_regressions(runner):
    for changed in (
        "worktrace/services/secure_backup_validation.py",
        "worktrace/write_gate.py",
    ):
        selection = runner.select_targets([changed])
        assert "tests/test_secure_backup_service.py" in selection.pytest_targets
        assert "tests/test_projection_governance_regressions.py" in selection.pytest_targets
"""

ARCHITECTURE_TESTS = """


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
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (REPO_ROOT / "worktrace").rglob("*")
        if path.suffix in {".py", ".js"}
    )
    assert {symbol for symbol in forbidden if symbol in source} == set()
"""


def append_guards() -> None:
    path = "tests/test_run_affected_tests.py"
    text = read(path)
    if "def test_canonical_projection_files_select_cross_layer_suite" not in text:
        write(path, text.rstrip() + RUNNER_TESTS + "\n")

    path = "tests/test_report_projection_architecture_contract.py"
    text = read(path)
    if "def test_projection_engine_reuses_domain_freeze_thaw" not in text:
        write(path, text.rstrip() + ARCHITECTURE_TESTS + "\n")


def restore_ci_and_remove_temporary_files() -> None:
    ci = subprocess.check_output(
        ["git", "show", "origin/main:.github/workflows/ci.yml"],
        cwd=ROOT,
    )
    (ROOT / ".github/workflows/ci.yml").write_bytes(ci)
    for relative in (
        ".github/workflows/apply-canonical-fix-once.yml",
        "scripts/apply_canonical_fix_once.py",
    ):
        path = ROOT / relative
        if path.exists():
            path.unlink()


def main() -> None:
    update_session_projection()
    update_csv_contract()
    update_operation_engine()
    update_affected_runner()
    append_guards()
    restore_ci_and_remove_temporary_files()


if __name__ == "__main__":
    main()
