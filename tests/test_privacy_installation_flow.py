from __future__ import annotations

from pathlib import Path

import pytest

from worktrace.privacy_policy import (
    PRIVACY_POLICY_EFFECTIVE_DATE,
    PRIVACY_POLICY_TEXT,
    PRIVACY_POLICY_VERSION,
)
from worktrace.services import privacy_gate_service
from worktrace.services.installation_metadata_store import get_privacy_notice_version

pytestmark = [pytest.mark.contract]

REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALLER_PATH = REPO_ROOT / "installer" / "WorkTrace.iss"
SPEC_PATH = REPO_ROOT / "WorkTrace.spec"
ENTRY_PATH = REPO_ROOT / "scripts" / "pyinstaller_entry.py"
POLICY_PATH = REPO_ROOT / "worktrace" / "privacy_policy_zh-CN.txt"


def _read(path: Path) -> str:
    assert path.is_file(), f"expected file: {path}"
    return path.read_text(encoding="utf-8")


def test_privacy_policy_v2_has_formal_data_lifecycle_sections():
    assert PRIVACY_POLICY_VERSION == "2"
    assert PRIVACY_POLICY_EFFECTIVE_DATE == "2026-08-15"
    assert PRIVACY_POLICY_TEXT == _read(POLICY_PATH).strip()

    for section in (
        "一、适用范围",
        "二、有迹处理哪些数据",
        "三、有迹默认不会记录什么",
        "四、处理数据的目的",
        "五、数据存储与保留期限",
        "六、本地数据与外部服务",
        "七、您如何控制自己的数据",
        "八、数据安全",
        "九、政策更新",
        "十、联系我们",
    ):
        assert section in PRIVACY_POLICY_TEXT

    assert "核心工作轨迹默认" in PRIVACY_POLICY_TEXT
    assert "“记录复制文字”默认关闭" in PRIVACY_POLICY_TEXT
    assert "最长保留 30 天" in PRIVACY_POLICY_TEXT
    assert "FD Work" in PRIVACY_POLICY_TEXT
    assert "所有数据默认保存在本机，不上传到云端" not in PRIVACY_POLICY_TEXT


def test_privacy_gate_rejects_stale_installer_policy_version(temp_db):
    assert privacy_gate_service.accept_privacy_notice_version("1") is False
    assert privacy_gate_service.is_privacy_notice_accepted() is False
    assert get_privacy_notice_version() == ""

    assert privacy_gate_service.accept_privacy_notice_version("2") is True
    assert privacy_gate_service.is_privacy_notice_accepted() is True
    assert get_privacy_notice_version() == "2"


def test_packaged_trace_contains_same_privacy_policy_resource():
    spec = _read(SPEC_PATH)
    assert "privacy_policy_zh-CN.txt" in spec
    assert "'worktrace'" in spec


def test_installer_requires_interactive_privacy_review_before_tasks():
    source = _read(INSTALLER_PATH)

    assert "CreateCustomPage" in source
    assert "wpWelcome" in source
    assert "隐私与数据" in source
    assert "LoadStringsFromFile" in source
    assert "LoadStringFromFile" not in source
    assert "我已阅读并了解《有迹隐私政策》及上述数据处理方式。" in source
    assert "PrivacyAcceptedCheck.Checked := False" in source
    assert "if not PrivacyAcceptedCheck.Checked then" in source
    assert "ConfigurePrivacyPage;" in source
    assert source.index("ConfigurePrivacyPage;") < source.index("ConfigureFDWorkTaskNotice;")


def test_silent_install_does_not_forge_privacy_acceptance():
    source = _read(INSTALLER_PATH)

    assert "if WizardSilent then" in source
    assert "PrivacyAcceptedForInstall := True" in source
    assert "if not PrivacyAcceptedForInstall then" in source
    assert "--accept-privacy-notice " in source
    assert "--source installer" in source
    assert "dontcopy noencryption" in source


def test_installer_privacy_acceptance_cli_is_narrow_and_version_checked():
    source = _read(ENTRY_PATH)

    assert '_PRIVACY_ACCEPT_ARGUMENT = "--accept-privacy-notice"' in source
    assert 'argv[2] != "--source"' in source
    assert 'argv[3] != "installer"' in source
    assert "accept_privacy_notice_version(argv[1])" in source
    assert "_run_installer_privacy_acceptance" in source
