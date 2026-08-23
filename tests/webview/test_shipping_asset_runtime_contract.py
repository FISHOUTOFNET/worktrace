from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

pytestmark = [pytest.mark.contract, pytest.mark.webview_static, pytest.mark.packaging]

ROOT = Path(__file__).resolve().parents[2]
UI_ROOT = ROOT / "worktrace" / "webview_ui"
INDEX = UI_ROOT / "index_fd_work_v5.html"
SYNC_SCRIPT = ROOT / "scripts" / "sync_webview_asset_revisions.py"


def _sync_module():
    spec = importlib.util.spec_from_file_location("sync_webview_asset_revisions", SYNC_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _local_assets(source: str) -> list[str]:
    scripts = re.findall(r'<script\s+src="([^"]+)"\s*>\s*</script>', source)
    styles = re.findall(
        r'<link\s+rel="stylesheet"\s+href="([^"]+)"\s*/?>',
        source,
    )
    return styles + scripts


def test_shipping_index_and_every_local_asset_use_shared_content_revision_keys():
    from worktrace import webview_main

    sync = _sync_module()
    source = INDEX.read_text(encoding="utf-8")
    assert source == sync.expected_index_source(source)

    assets = _local_assets(source)
    assert assets
    for asset_url in assets:
        parsed = urlsplit(asset_url)
        asset_path = UI_ROOT / parsed.path
        assert asset_path.is_file(), f"shipping asset does not exist: {parsed.path}"
        assert parse_qs(parsed.query) == {"v": [sync.content_revision(asset_path)]}, (
            f"stale or missing content revision for {parsed.path}"
        )

    index_url = webview_main._versioned_resource_url(INDEX)
    index_path, separator, revision = index_url.rpartition("?v=")
    assert separator == "?v="
    assert Path(index_path) == INDEX
    assert revision == sync.content_revision(INDEX)


def test_shipping_script_composition_contains_current_owners_in_order():
    source = INDEX.read_text(encoding="utf-8")
    scripts = [urlsplit(url).path for url in _local_assets(source) if url.startswith("js/")]
    required = [
        "js/core.js",
        "js/ui_components.js",
        "js/project_catalog.js",
        "js/timeline_delete_actions.js",
        "js/rules.js",
        "js/rules_render.js",
        "js/rules_create_panel_v5.js",
        "js/rules_rule_actions.js",
        "js/rules_delete_actions.js",
        "js/init_fd_work_v5.js",
        "js/shell_lifecycle.js",
        "js/ui_composition.js",
    ]
    assert [name for name in scripts if name in required] == required

    loaded = "\n".join((UI_ROOT / name).read_text(encoding="utf-8") for name in required)
    assert "rules_keyword_actions.js" not in source
    assert "rules_folder_actions.js" not in source
    assert "保留已有归类" in loaded
    assert "视同规则不存在" in loaded
