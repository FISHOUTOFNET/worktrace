from __future__ import annotations

from pathlib import Path

import pytest

from tests.support.application import FakeSettingsCapability, build_test_bridge
from worktrace.application_metadata import APPLICATION_METADATA
from worktrace.version import __version__

pytestmark = [pytest.mark.contract, pytest.mark.parallel_safe]

ROOT = Path(__file__).resolve().parents[1]


def test_application_metadata_uses_canonical_release_version() -> None:
    assert APPLICATION_METADATA.version == __version__
    assert APPLICATION_METADATA.release_channel == "beta"
    assert APPLICATION_METADATA.creator == "Sun Yi"


def test_status_projects_application_metadata_without_settings_dependency() -> None:
    settings = FakeSettingsCapability()
    settings.get_settings_privacy_status_side_effect = AssertionError(
        "application metadata must not depend on settings status"
    )
    bridge = build_test_bridge(settings=settings)

    result = bridge.get_status()

    assert result["application"] == {
        "version": __version__,
        "release_channel": "beta",
        "creator": "Sun Yi",
    }
    assert settings.get_settings_privacy_status_calls == []


def test_frontend_metadata_projection_is_read_only_and_responsive() -> None:
    source = (
        ROOT / "worktrace" / "webview_ui" / "js" / "ui_composition.js"
    ).read_text(encoding="utf-8")

    assert 'renderApplicationMetadata(statusResult.application)' in source
    assert '"v" + version' in source
    assert 'return "测试版"' in source
    assert 'creator ? "Created by " + creator' in source
    assert 'document.querySelector(".nav-footer")' in source
    assert 'document.querySelector(".settings-content")' in source
    assert '@media (max-width:959px){.application-version-label{display:none;}}' in source
    assert "App.bridge.getStatus()" not in source
    assert "window.pywebview.api" not in source
    assert "getSettingsPrivacyStatus" not in source
