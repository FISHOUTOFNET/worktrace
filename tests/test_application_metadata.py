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


def test_metadata_bridge_is_independent_of_settings_and_runtime_status() -> None:
    settings = FakeSettingsCapability()
    settings.get_settings_privacy_status_side_effect = AssertionError(
        "application metadata must not depend on settings status"
    )
    bridge = build_test_bridge(settings=settings)

    result = bridge.get_application_metadata()

    assert result == {
        "ok": True,
        "application": {
            "version": __version__,
            "release_channel": "beta",
            "creator": "Sun Yi",
        },
    }
    assert settings.get_settings_privacy_status_calls == []

    status = bridge.get_status()
    assert "application" not in status
    assert settings.get_settings_privacy_status_calls == []


def test_frontend_metadata_projection_uses_static_bootstrap_boundary() -> None:
    ui_root = ROOT / "worktrace" / "webview_ui"
    metadata_source = (ui_root / "js" / "application_metadata.js").read_text(
        encoding="utf-8"
    )
    init_source = (ui_root / "js" / "init_fd_work_v5.js").read_text(
        encoding="utf-8"
    )
    composition_source = (ui_root / "js" / "ui_composition.js").read_text(
        encoding="utf-8"
    )
    index_source = (ui_root / "index_fd_work_v5.html").read_text(encoding="utf-8")
    css_source = (ui_root / "application_metadata.css").read_text(encoding="utf-8")

    assert (
        'getApplicationMetadata: fixedBridgeMethod("get_application_metadata")'
        in init_source
    )
    assert "App.applicationMetadata.load()" in init_source
    assert "App.bridge.getApplicationMetadata()" in metadata_source
    assert "App.bridge.getStatus()" not in metadata_source
    assert "window.pywebview.api" not in metadata_source
    assert '"Created By " + creator' in metadata_source
    assert "statusResult.application" not in composition_source
    assert 'document.createElement("style")' not in composition_source

    for dom_id in (
        "application-version-label",
        "settings-about-application",
        "settings-application-version",
        "settings-application-creator",
    ):
        assert f'id="{dom_id}"' in index_source

    assert ".application-version-label" in css_source
    assert "@media (max-width: 959px)" in css_source
