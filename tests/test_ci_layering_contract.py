from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.contract, pytest.mark.parallel_safe]

ROOT = Path(__file__).resolve().parents[1]
CI_YML = ROOT / ".github" / "workflows" / "ci.yml"
VALIDATION_YML = ROOT / ".github" / "workflows" / "_validation.yml"
INSTALLER_YML = ROOT / ".github" / "workflows" / "installer-validation.yml"
PACKAGE_ACTION_YML = ROOT / ".github" / "actions" / "build-windows-package" / "action.yml"
RELEASE_BUILD = ROOT / "scripts" / "build_windows_release.ps1"
INSTALLER_SMOKE = ROOT / "scripts" / "ci" / "installer_runtime_smoke.ps1"


class TestStandardCiLayer:
    def test_ci_has_one_orchestration_job(self) -> None:
        source = CI_YML.read_text(encoding="utf-8")
        assert re.search(r"^  validate:\s*$", source, re.MULTILINE)
        assert not re.search(r"^  typography:\s*$", source, re.MULTILINE)

    def test_standard_ci_keeps_full_non_benchmark_suite(self) -> None:
        source = VALIDATION_YML.read_text(encoding="utf-8")
        assert '-m "not benchmark"' in source
        assert "scripts/run_pytest_ci.py" in source

    def test_standard_package_smoke_is_build_only(self) -> None:
        source = VALIDATION_YML.read_text(encoding="utf-8")
        assert "Build Windows executable and installer" in source
        assert "installer_runtime_smoke.ps1" not in source
        assert "smoke_installed_launch.ps1" not in source
        assert "Exercise installer runtime" not in source

    def test_typography_reuses_webview_runner(self) -> None:
        source = VALIDATION_YML.read_text(encoding="utf-8")
        assert "Run WebView Node tests" in source
        assert "Run FD Work Edge DOM fixture" in source
        assert "Render typography acceptance" in source
        assert "Upload typography render artifacts" in source


class TestSharedPackageBuild:
    def test_shared_action_exists(self) -> None:
        assert PACKAGE_ACTION_YML.is_file()

    def test_standard_and_installer_layers_use_same_build_action(self) -> None:
        validation = VALIDATION_YML.read_text(encoding="utf-8")
        installer = INSTALLER_YML.read_text(encoding="utf-8")
        shared = "uses: ./.github/actions/build-windows-package"
        assert shared in validation
        assert shared in installer

    def test_shared_action_delegates_to_one_release_build(self) -> None:
        action = PACKAGE_ACTION_YML.read_text(encoding="utf-8")
        release = RELEASE_BUILD.read_text(encoding="utf-8")

        assert r"scripts\build_windows_release.ps1" in action
        assert "python -m PyInstaller --noconfirm --clean WorkTrace.spec" not in action
        assert "& python -m PyInstaller --noconfirm --clean WorkTrace.spec" in release
        assert "build_windows_installer.ps1" in release
        assert "dist\\Trace.exe" in action
        assert "dist\\Trace-Setup.exe" in action


class TestInstallerValidationLayer:
    def test_installer_workflow_exists(self) -> None:
        assert INSTALLER_YML.is_file()

    def test_installer_pr_trigger_is_path_scoped(self) -> None:
        source = INSTALLER_YML.read_text(encoding="utf-8")
        pull_request = re.search(
            r"^  pull_request:\s*\n(?P<body>(?:    .*\n)+)",
            source,
            re.MULTILINE,
        )
        assert pull_request is not None
        assert "paths:" in pull_request.group("body")

    def test_installer_runs_on_main_tags_and_manual_dispatch(self) -> None:
        source = INSTALLER_YML.read_text(encoding="utf-8")
        assert "workflow_dispatch:" in source
        assert "branches: [main]" in source
        assert 'tags: ["v*"]' in source

    def test_installer_runtime_is_not_continue_on_error(self) -> None:
        source = INSTALLER_YML.read_text(encoding="utf-8")
        assert "Exercise installer runtime lifecycle" in source
        assert "continue-on-error" not in source

    def test_installer_runtime_script_keeps_upgrade_and_uninstall_contract(self) -> None:
        source = INSTALLER_SMOKE.read_text(encoding="utf-8")
        assert '-Operation "First install"' in source
        assert '-Operation "Upgrade install"' in source
        assert '-Operation "Uninstall"' in source
        assert "/NOFORCECLOSEAPPLICATIONS" in source
        assert "Upgrade left legacy WorkTrace.exe behind" in source
        assert "Uninstall left startup value behind" in source
