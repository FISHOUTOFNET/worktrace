from __future__ import annotations

import hashlib
import re
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

pytestmark = [pytest.mark.contract, pytest.mark.webview_static, pytest.mark.packaging]

ROOT = Path(__file__).resolve().parents[2]
UI_ROOT = ROOT / "worktrace" / "webview_ui"
INDEX = UI_ROOT / "index_fd_work_v5.html"


def _revision(path: Path) -> str:
    canonical_text = (
        path.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")
    )
    return hashlib.sha256(canonical_text.encode("utf-8")).hexdigest()[:16]


def _local_assets(source: str) -> list[str]:
    scripts = re.findall(r'<script\s+src="([^"]+)"\s*>\s*</script>', source)
    styles = re.findall(
        r'<link\s+rel="stylesheet"\s+href="([^"]+)"\s*/?>',
        source,
    )
    return styles + scripts


def test_shipping_index_and_every_local_asset_use_content_revision_cache_keys():
    from worktrace import webview_main

    source = INDEX.read_text(encoding="utf-8")
    assets = _local_assets(source)
    assert assets
    for asset_url in assets:
        parsed = urlsplit(asset_url)
        assert parsed.scheme == "" and parsed.netloc == ""
        assert parse_qs(parsed.query) == {
            "v": [_revision(UI_ROOT / parsed.path)]
        }, f"shipping asset must use its content hash: {asset_url}"

    index_url = webview_main._versioned_resource_url(INDEX)
    index_path, separator, revision = index_url.rpartition("?v=")
    assert separator == "?v="
    assert Path(index_path) == INDEX
    assert revision == _revision(INDEX)


def test_shipping_script_composition_contains_current_rule_owners_in_order():
    source = INDEX.read_text(encoding="utf-8")
    scripts = [urlsplit(url).path for url in _local_assets(source) if url.startswith("js/")]
    required = [
        "js/core.js",
        "js/ui_components.js",
        "js/rules.js",
        "js/rules_render.js",
        "js/rules_create_panel_v5.js",
        "js/rules_rule_actions.js",
        "js/rules_keyword_actions.js",
        "js/rules_folder_actions.js",
    ]
    assert [name for name in scripts if name in required] == required

    loaded = "\n".join((UI_ROOT / name).read_text(encoding="utf-8") for name in required)
    assert "规则删除后不再参与后续自动归类" not in loaded
    assert "既有历史归属保持不变" not in loaded
    assert "保留已有归类" in loaded
    assert "视同规则不存在" in loaded
