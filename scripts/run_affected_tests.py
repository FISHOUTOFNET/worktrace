#!/usr/bin/env python3
"""WorkTrace affected-test runner."""

from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

# Repo root = parent of this script's directory (scripts/).
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent

# Import smoke command run alongside pytest for WebView frontend changes.
# Kept as an argv list so it can be executed directly without shell quoting
# issues. Run as a separate command; never mixed into the pytest argv.
IMPORT_SMOKE_ARGV: list[str] = [
    "python",
    "-c",
    "import worktrace.webview_main; print('ok')",
]

# Light smoke set used when no changed files are detected (avoids silently
# running the full suite). Covers startup imports, the WebView bridge
# boundary, and the WebView static-contract suite.
SMOKE_FALLBACK_TARGETS: list[str] = [
    "tests/test_startup_imports.py",
    "tests/test_ui_backend_boundary.py",
    "tests/webview/",
]

COMMENT_HYGIENE_TARGET = "tests/test_comment_hygiene.py"
FAST_SUITE_COMMAND: list[str] = [
    "python",
    "-m",
    "pytest",
    "-m",
    "unit and not slow",
]
GOVERNANCE_COMMANDS: list[list[str]] = [
    ["python", "scripts/test_inventory.py", "--check"],
    ["python", "scripts/comment_hygiene.py", "--check"],
    [
        "python",
        "-m",
        "pytest",
        "tests/test_run_affected_tests.py",
        "tests/test_test_inventory.py",
        "tests/test_comment_hygiene.py",
        "tests/test_code_comment_hygiene.py",
    ],
]

# Broad-but-finite suite used when tests/conftest.py itself changes.
CONFTEST_BROAD_SUITE: list[str] = [
    "tests/test_db_migration.py",
    "tests/test_activity_service.py",
    "tests/test_rule_service.py",
    "tests/test_statistics_service.py",
    "tests/webview/",
]



RULES: list[dict] = [
    {
        "id": "A. WebView frontend resources",
        # Directory-level trigger so a new/renamed JS module never escapes the
        # WebView contract test set. The JS file list is parsed from index.html
        # at test time by tests/webview/static_helpers.py.
        "triggers": [
            "worktrace/webview_ui/index.html",
            "worktrace/webview_ui/styles.css",
            "worktrace/webview_ui/js/",
        ],
        "tests": [
            "tests/webview/",
            "tests/webview/test_heartbeat_projection_contract.py",
            "tests/webview/test_frontend_global_boundaries.py",
            "tests/webview/test_frontend_pure_render_contract.py",
            "tests/test_app_runtime_privacy_gate.py",
            "tests/test_short_activity_buffer.py",
            "tests/test_webview_bridge.py",
            "tests/test_ui_backend_boundary.py",
            "tests/test_bridge_refresh_state_and_projection.py",
            "tests/test_live_display_contract.py",
            "tests/test_live_display_project_transition_contract.py",
            "tests/test_display_model_anti_regression.py",
            "tests/test_live_product_semantics.py",
            "tests/test_run_affected_tests.py",
        ],
        "smoke": [IMPORT_SMOKE_ARGV],
        "warnings": [],
        "markers": ["webview_static and contract"],
    },
    {
        "id": "A2. ViewModel service / API facade",
        # The ViewModel service / API + Activity Display Model + live-display /
        # live-time services are the sole page-display payload constructors.
        # Any change must trigger the Overview / Timeline / Details /
        # Refresh State / live display / bridge boundary tests.
        "triggers": [
            "worktrace/services/view_model_service.py",
            "worktrace/services/project_activity_summary_service.py",
            "worktrace/api/view_model_api.py",
            "worktrace/contracts/",
            "worktrace/services/activity_display_model_service.py",
            "worktrace/services/activity_display_policy.py",
            "worktrace/services/activity_live_clock.py",
            "worktrace/services/activity_display_span.py",
            "worktrace/services/activity_row_overlay.py",
            "worktrace/services/live_display_service.py",
            "worktrace/services/live_time_service.py",
        ],
        "tests": [
            "tests/test_overview_bundle_and_export_contract.py",
            "tests/test_project_activity_summary_contract.py",
            "tests/test_app_runtime_privacy_gate.py",
            "tests/test_short_activity_buffer.py",
            "tests/test_bridge_refresh_state_and_projection.py",
            "tests/test_live_display_contract.py",
            "tests/test_live_display_project_transition_contract.py",
            "tests/test_display_model_anti_regression.py",
            "tests/test_live_product_semantics.py",
            "tests/scenarios/live_semantics/",
            "tests/test_run_affected_tests.py",
            "tests/webview/test_heartbeat_projection_contract.py",
            "tests/webview/test_frontend_global_boundaries.py",
            "tests/webview/test_frontend_pure_render_contract.py",
            "tests/test_ui_backend_boundary.py",
        ],
        "smoke": [IMPORT_SMOKE_ARGV],
        "warnings": [],
        "markers": ["live_display and contract"],
    },
    {
        "id": "B. WebView bridge",
        "triggers": [
            "worktrace/webview_ui/bridge.py",
            "worktrace/webview_ui/bridge_common.py",
            "worktrace/webview_ui/bridge_dialogs.py",
            "worktrace/webview_ui/bridge_overview.py",
            "worktrace/webview_ui/bridge_settings.py",
            "worktrace/webview_ui/bridge_statistics.py",
            "worktrace/webview_ui/bridge_timeline.py",
        ],
        "tests": [
            "tests/test_webview_bridge.py",
            "tests/test_webview_project_rules_bridge.py",
            "tests/test_webview_bridge_time_edit.py",
            "tests/test_webview_bridge_split.py",
            "tests/test_webview_bridge_merge.py",
            "tests/test_webview_bridge_visibility.py",
            "tests/test_webview_bridge_batch_project.py",
            "tests/test_webview_bridge_batch_note.py",
            "tests/test_webview_bridge_restore.py",
            "tests/test_webview_bridge_statistics.py",
            "tests/test_statistics_csv_export.py",
            "tests/test_settings_privacy_status.py",
            "tests/test_webview_entry.py",
            "tests/test_app_runtime_privacy_gate.py",
            "tests/test_ui_backend_boundary.py",
            "tests/test_bridge_refresh_state_and_projection.py",
            "tests/test_live_display_contract.py",
        ],
        "smoke": [],
        "warnings": [],
        "markers": ["integration and contract"],
    },
    {
        "id": "C1. Project Rules shared API contract helpers",
        "triggers": [
            "worktrace/api/_write_contract.py",
        ],
        "tests": [
            "tests/test_api_write_contract.py",
            "tests/test_project_rules_keyword_create.py",
            "tests/test_project_rules_keyword_delete.py",
            "tests/test_project_rules_keyword_edit.py",
            "tests/test_project_rules_folder_crud.py",
            "tests/test_project_rules_enable_disable.py",
            "tests/test_project_rules_project_lifecycle.py",
            "tests/test_project_rules_rule_impact.py",
            "tests/test_webview_project_rules_bridge.py",
            "tests/test_ui_backend_boundary.py",
        ],
        "smoke": [],
        "warnings": [
            "Shared Project Rules contract helper changed; running broad Project Rules suite.",
        ],
        "markers": ["contract and integration"],
    },
    {
        "id": "C2. Keyword rule API / service",
        "triggers": [
            "worktrace/api/rule_api.py",
            "worktrace/services/rule_service.py",
        ],
        "tests": [
            "tests/test_rule_service.py",
            "tests/test_project_rules_keyword_create.py",
            "tests/test_project_rules_keyword_delete.py",
            "tests/test_project_rules_keyword_edit.py",
            "tests/test_project_rules_enable_disable.py",
            "tests/test_project_rules_view.py",
            "tests/test_project_rules_rule_impact.py",
            "tests/test_webview_project_rules_bridge.py",
            "tests/test_ui_backend_boundary.py",
        ],
        "smoke": [],
        "warnings": [],
        "markers": ["contract and integration"],
    },
    {
        "id": "C3. Folder rule API / service",
        "triggers": [
            "worktrace/api/rule_api.py",
            "worktrace/services/folder_rule_service.py",
        ],
        "tests": [
            "tests/test_folder_rule_service.py",
            "tests/test_project_rules_folder_crud.py",
            "tests/test_project_rules_view.py",
            "tests/test_project_rules_rule_impact.py",
            "tests/test_webview_project_rules_bridge.py",
            "tests/test_ui_backend_boundary.py",
        ],
        "smoke": [],
        "warnings": [],
        "markers": ["contract and integration"],
    },
    {
        "id": "C4. Project lifecycle API / service",
        "triggers": [
            "worktrace/api/project_api.py",
            "worktrace/services/project_service.py",
            "worktrace/services/project_inference_service.py",
        ],
        "tests": [
            "tests/test_project_rules_project_lifecycle.py",
            "tests/test_project_rules_view.py",
            "tests/test_project_rules_rule_impact.py",
            "tests/test_webview_project_rules_bridge.py",
            "tests/test_ui_backend_boundary.py",
            "tests/test_project_rules_automatic_rules.py",
            "tests/test_activity_service.py",
            "tests/test_live_display_contract.py",
        ],
        "smoke": [],
        "warnings": [],
        "markers": ["contract and integration"],
    },
    {
        "id": "C5. Project Rules bridge",
        "triggers": [
            "worktrace/webview_ui/bridge_rules.py",
        ],
        "tests": [
            "tests/test_webview_project_rules_bridge.py",
            "tests/test_project_rules_rule_impact.py",
            "tests/test_ui_backend_boundary.py",
        ],
        "smoke": [],
        "warnings": [],
        "markers": ["contract and integration"],
    },
    {
        "id": "C6. Project Rules frontend / static",
        # Directory-level trigger so any Project Rules JS module change
        # (rename / add / remove) triggers the static contract suite.
        "triggers": [
            "worktrace/webview_ui/js/",
        ],
        "tests": [
            "tests/webview/test_project_rules_static_contract.py",
        ],
        "smoke": [IMPORT_SMOKE_ARGV],
        "warnings": [],
        "markers": ["webview_static and contract"],
    },
    {
        "id": "C7. Rule impact service",
        "triggers": [
            "worktrace/services/rule_impact_service.py",
        ],
        "tests": [
            "tests/test_project_rules_rule_impact.py",
            "tests/test_webview_project_rules_bridge.py",
            "tests/test_ui_backend_boundary.py",
        ],
        "smoke": [],
        "warnings": [],
        "markers": ["contract and integration"],
    },
    {
        "id": "C8. Automatic rules service",
        "triggers": [
            "worktrace/services/rule_automation_service.py",
        ],
        "tests": [
            "tests/test_project_rules_automatic_rules.py",
            "tests/test_webview_project_rules_bridge.py",
            "tests/test_ui_backend_boundary.py",
        ],
        "smoke": [],
        "warnings": [],
        "markers": ["contract and integration"],
    },
    {
        "id": "C9. Batch operations service",
        "triggers": [
            "worktrace/services/rule_batch_service.py",
        ],
        "tests": [
            "tests/test_project_rules_batch_operations.py",
            "tests/test_webview_project_rules_bridge.py",
            "tests/test_ui_backend_boundary.py",
        ],
        "smoke": [],
        "warnings": [],
        "markers": ["contract and integration"],
    },
    {
        "id": "D. Timeline API / service / bridge",
        "triggers": [
            "worktrace/api/timeline_api.py",
            "worktrace/services/timeline_service.py",
            "worktrace/services/project_activity_summary_service.py",
            "worktrace/services/session_boundary_service.py",
            "worktrace/webview_ui/bridge_timeline.py",
            "worktrace/webview_ui/js/timeline.js",
            "worktrace/webview_ui/js/timeline_correction.js",
        ],
        "tests": [
            "tests/test_timeline_service.py",
            "tests/test_project_activity_summary_contract.py",
            "tests/test_timeline_api_editing.py",
            "tests/test_webview_bridge.py",
            "tests/test_webview_bridge_time_edit.py",
            "tests/test_webview_bridge_split.py",
            "tests/test_webview_bridge_merge.py",
            "tests/test_webview_bridge_visibility.py",
            "tests/test_webview_bridge_batch_project.py",
            "tests/test_webview_bridge_batch_note.py",
            "tests/test_webview_bridge_restore.py",
            "tests/webview/test_timeline_static_contract.py",
            "tests/webview/test_timeline_correction_shell_contract.py",
            "tests/test_ui_backend_boundary.py",
        ],
        "smoke": [],
        "warnings": [],
        "markers": ["contract and integration"],
    },
    {
        "id": "E. Statistics / export",
        "triggers": [
            "worktrace/api/statistics_api.py",
            "worktrace/api/export_api.py",
            "worktrace/services/statistics_service.py",
            "worktrace/services/export_service.py",
            "worktrace/exports/excel_exporter.py",
            "worktrace/webview_ui/bridge_statistics.py",
            "worktrace/webview_ui/bridge_dialogs.py",
            "worktrace/webview_ui/js/statistics.js",
        ],
        "tests": [
            "tests/test_statistics_service.py",
            "tests/test_export_service.py",
            "tests/test_export_resource_fields.py",
            "tests/test_project_activity_summary_contract.py",
            "tests/test_webview_bridge_statistics.py",
            "tests/test_statistics_csv_export.py",
            "tests/webview/test_statistics_static_contract.py",
            "tests/test_webview_bridge.py",
            "tests/test_ui_backend_boundary.py",
        ],
        "smoke": [],
        "warnings": [],
        "markers": ["contract and integration"],
    },
    {
        "id": "F. Database / schema / migrations",
        "triggers": [
            "worktrace/db.py",
            "worktrace/schema.sql",
        ],
        "tests": [
            "tests/test_db_migration.py",
            "tests/test_activity_service.py",
            "tests/test_timeline_service.py",
            "tests/test_statistics_service.py",
            "tests/test_rule_service.py",
            "tests/test_folder_rule_service.py",
            "tests/test_project_rules_keyword_create.py",
            "tests/test_project_rules_keyword_delete.py",
            "tests/test_project_rules_keyword_edit.py",
            "tests/test_project_rules_project_lifecycle.py",
            "tests/test_project_rules_rule_impact.py",
            "tests/test_ui_backend_boundary.py",
        ],
        "smoke": [],
        "warnings": [
            "DB/schema changed; consider running full pytest before push.",
        ],
        "markers": ["db"],
    },
    {
        "id": "G. Security / crypto / backup",
        "triggers": [
            "worktrace/security/",
            "worktrace/services/secure_backup_service.py",
            "docs/v0.2-local-security-design.md",
            "docs/v0.2-boundary.md",
            "docs/research/v0.2-field-encryption-scan.md",
        ],
        "tests": [
            "tests/test_security_crypto.py",
            "tests/test_security_backup_format.py",
            "tests/test_security_key_manager.py",
            "tests/test_secure_backup_service.py",
            "tests/test_v02_local_security_design.py",
        ],
        "smoke": [],
        "warnings": [],
        "markers": ["security_privacy"],
    },
    {
        "id": "H. Collector / platform / resource model",
        "triggers": [
            "worktrace/collector/",
            "worktrace/services/runtime_activity_state_service.py",
            "worktrace/services/project_ownership_service.py",
            "worktrace/platforms/",
            "worktrace/resources/",
            "worktrace/path_utils.py",
        ],
        "tests": [
            "tests/test_collector.py",
            "tests/test_windows_adapter.py",
            "tests/test_resource_model.py",
            "tests/test_resource_helpers.py",
            "tests/test_path_utils.py",
            "tests/test_local_file_detector.py",
            "tests/test_startup_imports.py",
            "tests/test_app_runtime_privacy_gate.py",
            "tests/test_short_activity_buffer.py",
            "tests/test_project_ownership_pending.py",
            "tests/test_bridge_refresh_state_and_projection.py",
            "tests/test_live_display_project_transition_contract.py",
            "tests/test_display_model_anti_regression.py",
            "tests/test_live_product_semantics.py",
            "tests/scenarios/live_semantics/",
            "tests/webview/test_heartbeat_projection_contract.py",
            "tests/webview/test_frontend_global_boundaries.py",
            "tests/webview/test_frontend_pure_render_contract.py",
            "tests/test_ui_backend_boundary.py",
            "tests/test_run_affected_tests.py",
            "tests/test_live_display_contract.py",
        ],
        "smoke": [],
        "warnings": [],
        "markers": ["collector_runtime and integration"],
    },
    {
        "id": "I. Docs only",
        "triggers": [
            "README.md",
            "docs/",
            "architecture.md",
        ],
        "tests": [
            "tests/test_release_docs.py",
            "tests/webview/",
        ],
        "smoke": [],
        "warnings": [],
        "markers": ["contract"],
    },
    {
        "id": "J. Packaging / release files",
        "triggers": [
            "WorkTrace.spec",
            "scripts/build_windows_installer.ps1",
            "docs/release-validation.md",
            "docs/release-checklist.md",
            "requirements-dev.txt",
        ],
        "tests": [
            "tests/test_webview_packaging.py",
            "tests/test_release_docs.py",
            "tests/test_startup_imports.py",
        ],
        "smoke": [],
        "warnings": [
            "PyInstaller / installer builds remain manual release-validation "
            "steps and are not run by the affected runner.",
        ],
        "markers": ["packaging"],
    },
    {
        "id": "K1. Settings / Privacy WebView",
        "triggers": [
            "worktrace/api/settings_api.py",
            "worktrace/api/backup_api.py",
            "worktrace/webview_ui/bridge.py",
            "worktrace/webview_ui/bridge_settings.py",
            "worktrace/webview_ui/bridge_dialogs.py",
            "worktrace/webview_ui/index.html",
            "worktrace/webview_ui/js/",
            "worktrace/webview_ui/styles.css",
            "WorkTrace.spec",
            "tests/webview/static_helpers.py",
        ],
        "tests": [
            "tests/test_settings_privacy_status.py",
            "tests/webview/test_settings_static_contract.py",
            "tests/test_webview_entry.py",
            "tests/test_app_runtime_privacy_gate.py",
            "tests/test_ui_backend_boundary.py",
            "tests/webview/test_frontend_global_boundaries.py",
            "tests/test_webview_packaging.py",
            "tests/test_run_affected_tests.py",
            "tests/test_bridge_refresh_state_and_projection.py",
            "tests/webview/test_heartbeat_projection_contract.py",
        ],
        "smoke": [IMPORT_SMOKE_ARGV],
        "warnings": [],
        "markers": ["security_privacy", "webview_static and contract"],
    },
    {
        "id": "K2. WebView main / startup gate",
        "triggers": [
            "worktrace/webview_main.py",
            "worktrace/main.py",
            "worktrace/api/app_api.py",
            "worktrace/runtime/app_runtime.py",
            "worktrace/services/runtime_activity_state_service.py",
        ],
        "tests": [
            "tests/test_webview_entry.py",
            "tests/test_startup_imports.py",
            "tests/test_ui_backend_boundary.py",
            "tests/test_settings_privacy_status.py",
            "tests/test_app_runtime_privacy_gate.py",
            "tests/test_run_affected_tests.py",
        ],
        "smoke": [IMPORT_SMOKE_ARGV],
        "warnings": [],
        "markers": ["collector_runtime and integration"],
    },
    {
        "id": "L1. Context assignment service",
        "triggers": [
            "worktrace/services/context_service.py",
        ],
        "tests": [
            "tests/test_context_service.py",
            "tests/test_timeline_service.py",
            "tests/test_ui_backend_boundary.py",
            "tests/test_live_display_contract.py",
        ],
        "smoke": [],
        "warnings": [],
        "markers": ["contract and integration"],
    },
    {
        "id": "M. Live display service / API",
        "triggers": [
            "worktrace/services/live_display_service.py",
            "worktrace/services/activity_display_model_service.py",
            "worktrace/services/activity_display_policy.py",
            "worktrace/services/activity_live_clock.py",
            "worktrace/services/activity_display_span.py",
            "worktrace/services/activity_row_overlay.py",
            "worktrace/services/live_time_service.py",
            "worktrace/services/activity_service.py",
            "worktrace/webview_ui/bridge_overview.py",
            "worktrace/webview_ui/bridge_timeline.py",
            "worktrace/services/timeline_service.py",
            "worktrace/services/statistics_service.py",
            "worktrace/services/export_service.py",
        ],
        "tests": [
            "tests/test_overview_bundle_and_export_contract.py",
            "tests/test_bridge_refresh_state_and_projection.py",
            "tests/test_live_display_contract.py",
            "tests/test_live_display_project_transition_contract.py",
            "tests/test_display_model_anti_regression.py",
            "tests/test_live_product_semantics.py",
            "tests/scenarios/live_semantics/",
            "tests/webview/test_heartbeat_projection_contract.py",
            "tests/webview/test_frontend_global_boundaries.py",
            "tests/webview/test_frontend_pure_render_contract.py",
            "tests/test_statistics_service.py",
            "tests/test_timeline_service.py",
            "tests/test_live_time_service.py",
            "tests/test_webview_bridge.py",
            "tests/test_ui_backend_boundary.py",
            "tests/test_activity_service.py",
            "tests/webview/test_timeline_static_contract.py",
            "tests/test_run_affected_tests.py",
        ],
        "smoke": [IMPORT_SMOKE_ARGV],
        "warnings": [],
        "markers": ["live_display and contract"],
    },
    {
        "id": "N. Activity lifecycle boundary",
        "triggers": [
            "worktrace/services/activity_lifecycle_service.py",
            "worktrace/services/activity_service.py",
            "worktrace/services/recovery_service.py",
            "worktrace/services/runtime_activity_state_service.py",
            "worktrace/collector/",
            "worktrace/runtime/app_runtime.py",
        ],
        "tests": [
            "tests/test_activity_lifecycle_service.py",
            "tests/test_activity_lifecycle_boundary.py",
            "tests/test_activity_service.py",
            "tests/test_collector.py",
            "tests/test_state_machine.py",
            "tests/test_clipboard_service.py",
            "tests/test_recovery_service.py",
            "tests/test_app_runtime_privacy_gate.py",
            "tests/test_project_rules_automatic_rules.py",
            "tests/test_live_display_contract.py",
            "tests/test_live_product_semantics.py",
            "tests/test_timeline_service.py",
            "tests/test_statistics_service.py",
            "tests/test_run_affected_tests.py",
            "tests/test_ui_backend_boundary.py",
        ],
        "smoke": [],
        "warnings": [],
        "markers": ["collector_runtime and integration"],
    },
    {
        "id": "O. Comment hygiene gate",
        "triggers": [
            "comment_policy.json",
            "scripts/comment_hygiene.py",
            ".ai/comment-hygiene-fixer.md",
        ],
        "tests": [
            COMMENT_HYGIENE_TARGET,
            "tests/test_run_affected_tests.py",
        ],
        "smoke": [],
        "warnings": [],
        "markers": ["unit"],
    },
]


@dataclass
class Selection:
    """Result of mapping changed files to test targets.

    Attributes:
        changed_files: normalized repo-relative changed paths.
        pytest_targets: ordered, de-duplicated pytest target list (files or
            directories). Stable: first occurrence wins on dedup.
        marker_exprs: marker shard expressions associated with the matched
            rules. Diagnostic/selection hints only; the default command still
            runs concrete targets so unmarked tests are not skipped.
        smoke_commands: extra non-pytest commands to run, each an argv list.
        warnings: human-readable notes about the selection (e.g. DB change,
            unknown source, packaging reminder).
    """

    changed_files: list[str] = field(default_factory=list)
    pytest_targets: list[str] = field(default_factory=list)
    marker_exprs: list[str] = field(default_factory=list)
    smoke_commands: list[list[str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# Pure selection logic (no filesystem / git access; unit-testable).


def _normalize(path: str) -> str:
    """Normalize a changed-file path to repo-relative forward slashes."""
    if not path:
        return ""
    path = path.replace("\\", "/")
    # Drop a leading "./" that some git configurations emit.
    while path.startswith("./"):
        path = path[2:]
    return path


def _matches_trigger(changed: str, trigger: str) -> bool:
    """Return True if ``changed`` matches a trigger (exact or dir prefix)."""
    if trigger.endswith("/"):
        return changed.startswith(trigger) or changed == trigger.rstrip("/")
    return changed == trigger


def select_targets(changed_files: Iterable[str]) -> Selection:
    """Map changed files to a conservative, ordered, de-duplicated test set.

    Sections A..N (C refined into C1..C9) are matched against
    every non-test changed file. Test-file
    changes (section L) are matched first so the most directly-affected test
    runs first. Unknown ``worktrace/`` source changes (section K) fall back
    to a startup + boundary smoke set plus a warning. When nothing changed,
    a light smoke set is returned instead of the full suite.
    """
    normalized = [_normalize(p) for p in changed_files if p and p.strip()]
    # De-duplicate input while preserving order.
    seen_in: set[str] = set()
    files: list[str] = []
    for f in normalized:
        if f and f not in seen_in:
            seen_in.add(f)
            files.append(f)

    targets: list[str] = []
    smoke: list[list[str]] = []
    markers: list[str] = []
    warnings: list[str] = []
    seen_t: set[str] = set()
    seen_s: set[tuple[str, ...]] = set()
    seen_m: set[str] = set()

    def add_target(t: str) -> None:
        if t not in seen_t:
            seen_t.add(t)
            targets.append(t)

    def add_smoke(argv: list[str]) -> None:
        key = tuple(argv)
        if key not in seen_s:
            seen_s.add(key)
            smoke.append(list(argv))

    def add_marker(expr: str) -> None:
        if expr not in seen_m:
            seen_m.add(expr)
            markers.append(expr)

    def add_warning(w: str) -> None:
        if w not in warnings:
            warnings.append(w)

    test_changes: list[str] = []
    source_changes: list[str] = []
    for c in files:
        if c.startswith("tests/"):
            test_changes.append(c)
        else:
            source_changes.append(c)

    # L. Test file changes: run the changed test file directly.
    for c in test_changes:
        if c == "tests/conftest.py":
            for t in CONFTEST_BROAD_SUITE:
                add_target(t)
            add_warning("tests/conftest.py changed; running broad suite.")
        elif c.startswith("tests/webview/"):
            add_target(c)
            add_target("tests/webview/")
        elif c in (
            "tests/support/live_semantics_harness.py",
            "tests/support/collector_stream.py",
        ):
            add_target("tests/scenarios/live_semantics/")
            add_target("tests/test_live_product_semantics.py")
            add_target("tests/test_display_model_anti_regression.py")
            if c.endswith("collector_stream.py"):
                add_target("tests/test_collector.py")
                add_target("tests/test_short_activity_buffer.py")
        elif c == COMMENT_HYGIENE_TARGET:
            add_target(c)
            add_target("tests/test_run_affected_tests.py")
        else:
            add_target(c)

    # A..L for source / docs / packaging files.
    for c in source_changes:
        matched = False
        for rule in RULES:
            if any(_matches_trigger(c, t) for t in rule["triggers"]):
                matched = True
                for t in rule["tests"]:
                    add_target(t)
                for s in rule["smoke"]:
                    add_smoke(s)
                for w in rule["warnings"]:
                    add_warning(w)
                for m in rule.get("markers", []):
                    add_marker(m)
        # K. Unknown worktrace/ source change: smoke + boundary + warn.
        if not matched and c.startswith("worktrace/"):
            add_target("tests/test_startup_imports.py")
            add_target("tests/test_ui_backend_boundary.py")
            add_warning(
                "Unknown worktrace/ source changed; run targeted tests or "
                "full pytest before push."
            )

    # No changed files: light smoke set (never silently full suite).
    if not files:
        for t in SMOKE_FALLBACK_TARGETS:
            add_target(t)
        add_smoke(IMPORT_SMOKE_ARGV)
        add_warning(
            "No changed files detected; running light smoke set. "
            "Use --all for full pytest."
        )

    add_target(COMMENT_HYGIENE_TARGET)

    return Selection(
        changed_files=files,
        pytest_targets=targets,
        marker_exprs=markers,
        smoke_commands=smoke,
        warnings=warnings,
    )


def existing_targets(targets: Iterable[str], repo_root: Path) -> list[str]:
    """Filter ``targets`` to those that exist on disk under ``repo_root``.

    Directory targets (trailing ``/``) and exact file targets are both
    accepted. Nonexistent suggestions are silently skipped so a stale mapping
    never makes the runner fail.
    """
    root = Path(repo_root)
    out: list[str] = []
    for t in targets:
        clean = t.replace("\\", "/").rstrip("/")
        if not clean:
            continue
        candidate = root / clean
        if candidate.exists():
            out.append(t)
    return out


def build_pytest_command(targets: Iterable[str], extra_args: Iterable[str]) -> list[str]:
    """Build the ``python -m pytest`` argv from targets plus passthrough args.

    An empty ``targets`` list yields a bare ``python -m pytest`` (full suite),
    which is the shape used by the ``--all`` fallback.
    """
    cmd: list[str] = ["python", "-m", "pytest"]
    cmd.extend(targets)
    cmd.extend(extra_args)
    return cmd


# Git integration.


def _is_git_repo(repo_root: Path) -> bool:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return False
    return result.returncode == 0 and result.stdout.strip() == "true"


def _git_changed_files(repo_root: Path, base: str, staged: bool) -> list[str]:
    """Return repo-relative changed file paths from ``git diff --name-only``."""
    cmd = ["git", "diff", "--name-only"]
    if staged:
        cmd.append("--cached")
    cmd.append(base)
    result = subprocess.run(
        cmd,
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        # Surface git's own message so the user can diagnose the base ref.
        sys.stderr.write(result.stderr)
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


# CLI.


def _split_passthrough(argv: list[str]) -> tuple[list[str], list[str]]:
    """Split argv into own options and pytest passthrough (after ``--``)."""
    if "--" in argv:
        idx = argv.index("--")
        return argv[:idx], argv[idx + 1:]
    return argv, []


def _format_argv(argv: list[str]) -> str:
    return shlex.join(argv)


def _print_selection(sel: Selection, final_command: str | None) -> None:
    print("Changed files:")
    if sel.changed_files:
        for f in sel.changed_files:
            print(f"  - {f}")
    else:
        print("  (none detected)")
    print()
    print("Selected test targets:")
    if sel.pytest_targets:
        for t in sel.pytest_targets:
            print(f"  - {t}")
    else:
        print("  (none)")
    print()
    print("Marker shards:")
    if sel.marker_exprs:
        for expr in sel.marker_exprs:
            print(f"  - {expr}")
    else:
        print("  (none)")
    print()
    if sel.smoke_commands:
        print("Smoke commands:")
        for s in sel.smoke_commands:
            print(f"  - {_format_argv(s)}")
        print()
    if sel.warnings:
        print("Warnings:")
        for w in sel.warnings:
            print(f"  - {w}")
        print()
    if final_command is not None:
        print("Final command:")
        print(f"  {final_command}")
        print()


def _print_command_list(title: str, commands: list[list[str]], warnings: list[str] | None = None) -> None:
    print(title)
    if warnings:
        print("Warnings:")
        for warning in warnings:
            print(f"  - {warning}")
        print()
    print("Commands:")
    for command in commands:
        print(f"  - {_format_argv(command)}")
    print()


def _run_commands(commands: list[list[str]]) -> int:
    for command in commands:
        print(f"Running: {_format_argv(command)}")
        rc = subprocess.run(command, cwd=str(REPO_ROOT)).returncode
        if rc != 0:
            return rc
    return 0


def main(argv: list[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    own, extra = _split_passthrough(raw)

    parser = argparse.ArgumentParser(
        description=(
            "Run the subset of WorkTrace tests affected by the current "
            "workspace changes. Pure stdlib; no new dependencies."
        ),
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="Print changed files and selected targets only; do not run pytest.",
    )
    parser.add_argument(
        "--print-only",
        action="store_true",
        help="Print the final pytest command without executing it.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Run the full `python -m pytest` suite (explicit fallback).",
    )
    parser.add_argument(
        "--fast",
        action="store_true",
        help=(
            "Run marker-covered fast feedback: "
            "`python -m pytest -m \"unit and not slow\"`."
        ),
    )
    parser.add_argument(
        "--governance",
        action="store_true",
        help="Run lightweight test/comment/runner governance checks.",
    )
    parser.add_argument(
        "--files",
        nargs="+",
        default=None,
        help=(
            "Use the provided repo-relative changed files instead of git diff. "
            "Useful for CI hooks and one-off targeted validation."
        ),
    )
    parser.add_argument(
        "--base",
        default="HEAD",
        help="Diff base ref (default: HEAD).",
    )
    parser.add_argument(
        "--staged",
        action="store_true",
        help="Only consider staged changes (git diff --cached).",
    )
    opts = parser.parse_args(own)

    if sum(bool(flag) for flag in (opts.all, opts.fast, opts.governance)) > 1:
        parser.error("--all, --fast, and --governance are mutually exclusive")

    if opts.fast:
        command = list(FAST_SUITE_COMMAND) + extra
        warnings = [
            "Fast suite is marker-covered fast feedback only; marker coverage "
            "is incremental and does not replace affected or full pytest.",
        ]
        _print_command_list("Fast suite", [command], warnings)
        if opts.list or opts.print_only:
            return 0
        return _run_commands([command])

    if opts.governance:
        commands = [list(command) for command in GOVERNANCE_COMMANDS]
        if extra:
            commands[-1] = commands[-1] + extra
        _print_command_list("Governance suite", commands)
        if opts.list or opts.print_only:
            return 0
        return _run_commands(commands)

    # --all: explicit full-suite fallback.
    if opts.all:
        command = build_pytest_command([], extra)
        _print_selection(
            Selection(warnings=["Full-suite fallback (--all)."]),
            _format_argv(command),
        )
        if opts.list or opts.print_only:
            return 0
        return subprocess.run(command, cwd=str(REPO_ROOT)).returncode

    if opts.files:
        changed = list(opts.files)
    else:
        # Require a git repo. Never silently run the full suite.
        if not _is_git_repo(REPO_ROOT):
            sys.stderr.write(
                "ERROR: not a git repository (or git is not on PATH).\n"
                "Run `python -m pytest` explicitly, or pass --files with "
                "repo-relative paths, or use "
                "`python scripts/run_affected_tests.py --all` for the "
                "full suite.\n"
            )
            return 2
        changed = _git_changed_files(REPO_ROOT, opts.base, opts.staged)
    sel = select_targets(changed)
    targets = existing_targets(sel.pytest_targets, REPO_ROOT)

    if not targets:
        # All suggested targets were filtered out (mapping staleness) or
        # nothing produced targets. Do not silently fall back to full suite.
        _print_selection(sel, None)
        sys.stderr.write(
            "No existing test targets selected. Run `python -m pytest` "
            "explicitly with a target, or use --all.\n"
        )
        return 0

    command = build_pytest_command(targets, extra)

    if opts.list:
        _print_selection(sel, None)
        return 0
    if opts.print_only:
        _print_selection(sel, _format_argv(command))
        return 0

    _print_selection(sel, _format_argv(command))

    # Run smoke commands first (auxiliary); failures are reported but do not
    # block pytest. The function returns pytest's exit code per spec.
    for smoke_argv in sel.smoke_commands:
        print(f"Running smoke: {_format_argv(smoke_argv)}")
        smoke_rc = subprocess.run(smoke_argv, cwd=str(REPO_ROOT)).returncode
        if smoke_rc != 0:
            print(f"Smoke command failed (exit {smoke_rc}); continuing to pytest.")

    print(f"Running: {_format_argv(command)}")
    return subprocess.run(command, cwd=str(REPO_ROOT)).returncode


if __name__ == "__main__":
    raise SystemExit(main())
